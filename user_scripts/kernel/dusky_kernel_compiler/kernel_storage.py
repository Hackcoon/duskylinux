"""Machine-local storage configuration and recoverable RAM workspaces."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tomllib


class StorageError(ValueError):
    pass


def load_settings(path: Path, cache_home: Path, build_dir: Path | None = None) -> dict:
    raw = tomllib.loads(path.read_text())
    keys = {'persistent_dir', 'packages_dir', 'ccache_dir', 'thinlto_dir', 'zram_dir', 'ram_reserve_gib'}
    if set(raw) != {'storage'} or not isinstance(raw['storage'], dict) or set(raw['storage']) != keys:
        raise StorageError(f'{path}: expected [storage] with keys: {", ".join(sorted(keys))}')
    s = dict(raw['storage'])
    for key in keys - {'ram_reserve_gib'}:
        if not isinstance(s[key], str):
            raise StorageError(f'{path}: storage.{key} must be a string')
    if type(s['ram_reserve_gib']) is not int or s['ram_reserve_gib'] < 0:
        raise StorageError('storage.ram_reserve_gib must be a nonnegative integer')
    def expand(value):
        return Path(os.path.expandvars(value)).expanduser().resolve()
    s['persistent_dir'] = expand(str(build_dir) if build_dir is not None else os.environ.get('DUSKY_BUILD_DIR') or s['persistent_dir'] or str(cache_home / 'dusky-kernel'))
    for key, env, child in [('packages_dir', 'DUSKY_PKGDEST', 'packages'),
                            ('ccache_dir', 'CCACHE_DIR', 'ccache'),
                            ('thinlto_dir', 'DUSKY_THINLTO_CACHE', 'thinlto-cache')]:
        s[key] = expand(os.environ.get(env) or s[key] or str(s['persistent_dir'] / child))
    if not s['zram_dir']:
        raise StorageError('storage.zram_dir must name a RAM workspace')
    s['zram_dir'] = expand(s['zram_dir'])
    paths = [s['persistent_dir'] / 'src', s['persistent_dir'] / 'seeds',
             s['packages_dir'], s['ccache_dir'], s['thinlto_dir'], s['zram_dir']]
    for i, a in enumerate(paths):
        for b in paths[i + 1:]:
            if a == b or a in b.parents or b in a.parents:
                raise StorageError(f'Storage locations must not overlap: {a} and {b}')
    return s


def ram_mount(path: Path) -> bool:
    parent = path
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    cp = subprocess.run(['findmnt', '-J', '-o', 'SOURCE,FSTYPE', '--target', str(parent)],
                        text=True, capture_output=True, check=False)
    if cp.returncode:
        return False
    rows = json.loads(cp.stdout).get('filesystems', [])
    return bool(rows and (rows[0]['fstype'] == 'tmpfs' or rows[0]['source'].startswith('/dev/zram')))


def sync_tree(source: Path, dest: Path, run) -> None:
    source.mkdir(parents=True, exist_ok=True)
    dest.mkdir(parents=True, exist_ok=True)
    run(['rsync', '-a', '--delete', '--exclude=pacman/', '--exclude=*.pkg.tar.*', '--', str(source) + '/', str(dest) + '/'])


@contextmanager
def ram_workspace(settings: dict, run, note, save_run=None):
    """Caller holds the persistent workspace lock throughout restore/build/save."""
    persistent = settings['persistent_dir']
    ram = settings['zram_dir'] / hashlib.sha256(str(persistent).encode()).hexdigest()[:12]
    if not ram_mount(ram):
        raise StorageError(f'{ram}: not on a mounted tmpfs or ZRAM device')
    pairs = [(persistent / 'src', ram / 'src'), (persistent / 'seeds', ram / 'seeds'),
             (settings['thinlto_dir'], ram / 'thinlto-cache'), (settings['ccache_dir'], ram / 'ccache')]
    for disk, volatile in pairs:
        if disk == ram or disk in ram.parents or ram in disk.parents or ram_mount(disk):
            raise StorageError(f'Persistent storage must be on disk and separate from RAM workspace: {disk}')
    if ram_mount(settings['packages_dir']):
        raise StorageError('Package destination must be persistent disk storage')
    ram.mkdir(parents=True, exist_ok=True)
    marker = ram / '.unsaved'
    # A failed checkpoint must never be overwritten by an older disk copy.
    if marker.exists():
        raise StorageError(f'Unsaved RAM workspace at {ram}; copy its src/seeds/caches to persistent storage before removing {marker}')
    note(f'Restoring build objects and caches from {persistent} to {ram}')
    for disk, volatile in pairs:
        sync_tree(disk, volatile, run)
    marker.touch()
    try:
        yield ram
    finally:
        note(f'Saving changed build objects and caches to {persistent}; do not reboot until finished')
        for disk, volatile in pairs:
            sync_tree(volatile, disk, save_run or run)
        marker.unlink()
