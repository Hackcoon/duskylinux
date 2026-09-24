"""Real Btrfs regression tests on two disposable loop images.
Run explicitly: sudo python tests/snapper_btrfs.py
All mounts are isolated with unshare; existing filesystems are not modified.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "dusky_snapshot_manager.py"


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run this integration test with sudo.")
    if sys.argv[1:] != ["--isolated"]:
        os.execvp("unshare", ["unshare", "--mount", "--propagation", "private",
                             sys.executable, str(Path(__file__).resolve()), "--isolated"])
    spec = importlib.util.spec_from_file_location("dusky", SCRIPT)
    d = importlib.util.module_from_spec(spec)
    sys.modules["dusky"] = d
    spec.loader.exec_module(d)
    base = Path(tempfile.mkdtemp(prefix="dusky-snapper-", dir="/var/tmp"))
    a, b = base / "a", base / "b"
    d.RUN_DIR = base / "run"
    d.MNT_ROOT = d.RUN_DIR / "mnt"
    d.LOCK_PATH = d.RUN_DIR / "lock"
    try:
        for mount in (a, b):
            image = base / (mount.name + ".img")
            with image.open("wb") as stream:
                stream.truncate(512 * 1024 * 1024)
            subprocess.run(["mkfs.btrfs", "-q", str(image)], check=True)
            mount.mkdir()
            subprocess.run(["mount", "-o", "loop", str(image), str(mount)], check=True)
            subprocess.run(["btrfs", "subvolume", "create", str(mount / "@test")], check=True)
        def cmd(*args): return d.run(*map(str,args),check=True).text
        
        def make(top, name):
         path=top/name
         cmd('btrfs','subvolume','create',path)
         (path/'marker').write_text(name)
         return path
        
        alt = base / 'snapper-root'
        (alt / 'etc/conf.d').mkdir(parents=True)
        (alt / 'etc/conf.d/snapper').write_text('SNAPPER_CONFIGS=""\n')
        (alt / 'etc/snapper/configs').mkdir(parents=True)
        cmd('mount', '--bind', alt / 'etc/snapper', '/etc/snapper')
        cmd('mount', '--bind', alt / 'etc/conf.d', '/etc/conf.d')
        for name, top in (('left', a), ('right', b)):
            source = make(top, '@' + name)
            target = alt / name; target.mkdir()
            cmd('mount', '--bind', source, target)
            cmd('snapper', '--no-dbus', '-c', name, 'create-config', target)
        original_run = d.run
        def isolated_run(*args, **kwargs):
            if args[0] == 'snapper':
                args = ('snapper', '--no-dbus', *args[1:])
            return original_run(*args, **kwargs)
        with patch.object(d, 'run', side_effect=isolated_run), \
             patch.object(d, 'snapper_config_subvolume', side_effect=lambda name: str(alt / name)):
            d.cmd_create_pair('left', 'right', 'test pair')
            left = d.snapshot_rows('left'); right = d.snapshot_rows('right')
            assert len(left) == len(right) == 1
            pair = d.find_pair('left', 'right', left_id_hint=left[0]['id'])
            assert pair.exact and pair.right_id == right[0]['id']
            d.cmd_delete_pair('left', pair.left_id, 'right', pair.right_id)
            assert not d.snapshot_rows('left') and not d.snapshot_rows('right')
            print('PASS real Snapper create/list/pair/delete with isolated configuration', flush=True)
            try:
                d.cmd_create_pair('left', 'missing', 'expected failure')
            except d.DuskyError:
                pass
            else:
                raise AssertionError('invalid second config succeeded')
            assert not d.snapshot_rows('left')
            print('PASS failed second Snapper create removes the first half', flush=True)
            def interrupted_run(*args, **kwargs):
                if args[0] == 'snapper' and 'right' in args and 'create' in args:
                    raise d.DuskyError('injected timeout')
                return isolated_run(*args, **kwargs)
            with patch.object(d, 'run', side_effect=interrupted_run):
                try:
                    d.cmd_create_pair('left', 'right', 'interrupted pair')
                except d.DuskyError:
                    pass
            assert not d.snapshot_rows('left'), 'exception left an unreported half-pair'
            print('PASS exception during pair creation compensates the first half', flush=True)
    finally:
        for target in ('/etc/conf.d', '/etc/snapper'):
            if d.is_mountpoint(target):
                subprocess.run(['umount', target], check=True)
        # Never traverse or delete a filesystem until all our mounts are gone.
        mounts = [e["target"] for e in d.findmnt_entries()
                  if str(e.get("target", "")).startswith(str(base) + "/")]
        for mount in sorted(set(mounts), key=len, reverse=True):
            subprocess.run(["umount", "--", mount], check=True)
        shutil.rmtree(base)
    print("ALL SNAPPER INTEGRATION CHECKS PASSED")


if __name__ == "__main__":
    main()
