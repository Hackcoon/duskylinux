"""Real Btrfs regression tests on two disposable loop images.
Run explicitly: sudo python tests/stress_btrfs.py
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
    base = Path(tempfile.mkdtemp(prefix="dusky-stress-", dir="/var/tmp"))
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
        
        fa, fb = d.filesystem_of(str(a)), d.filesystem_of(str(b))
        # Check the previously uncovered staging-deletion path on an actual mount.
        staging = b / '.btrfs_recv_mounted'
        staging.mkdir()
        victim = make(b, '.btrfs_recv_mounted/inflight')
        mount = base / 'busy'; mount.mkdir()
        cmd('mount', '--bind', victim, mount)
        d._purge_staging(staging)
        preserved = victim.exists()
        cmd('umount', mount)
        print('MOUNTED_RECEIVE_PRESERVED', preserved, flush=True)
        assert preserved, 'receive staging cleanup deleted a mounted subvolume'

        # The mounted alias of a retired root must never become a new restore target.
        live = make(a, '@repeated')
        clone = make(a, '@repeated_dusky_new_1_20260925T000000Z')
        cmd('mount', '--bind', live, mount)
        d.rename_exchange(live, clone)
        with patch.object(d, 'snapper_config_subvolume', return_value=str(mount)):
            try:
                d.resolve_target('test', '1')
            except d.DuskyError as exc:
                assert 'reboot' in str(exc).lower() or 'retired' in str(exc).lower(), str(exc)
            else:
                raise AssertionError('second restore accepted a retired live root')
        cmd('umount', mount)
        print('PASS repeated restore is rejected before source resolution', flush=True)

        # Stacked mounts must resolve to the visible top layer, even across filesystems.
        low, high = make(a, '@low'), make(b, '@high')
        cmd('mount', '--bind', low, mount)
        cmd('mount', '--bind', high, mount)
        assert d.filesystem_of(str(mount)).uuid == fb.uuid
        assert d.active_subvol(str(mount))[1] == d.subvol_show(high).subvolid
        cmd('umount', mount); cmd('umount', mount)
        print('PASS stacked mount identity', flush=True)

        # Crash immediately after each persistence/rename/default boundary.
        from functools import wraps
        import signal
        hooks = ('write_file_durable', 'btrfs_sync', 'rename_exchange_at',
                 'rename_noreplace_at', 'set_default_subvolid')
        completed = 0
        for mode in ('activate', 'unwind', 'finalise'):
            for cut in range(1, 70):
                plans = []
                with ExitStack() as stack:
                    for n, (fs, top) in enumerate(((fa, a), (fb, b))):
                        name = f'@{mode}{cut}_{n}'
                        live = make(top, name)
                        source = top / (name + '_source')
                        cmd('btrfs', 'subvolume', 'snapshot', '-r', live, source)
                        old = d.subvol_show(live).subvolid
                        d.set_default_subvolid(old, top)
                        target = d.RestoreTarget('test', '1', '/fake', fs, name, old, '')
                        plan = d.RestorePlan(target, top, '', name,
                            name + '_dusky_new_1_20260925T000000Z',
                            name + '_to_delete_20260925T000000Z', source.name,
                            default_before=old)
                        cmd('btrfs', 'subvolume', 'snapshot', source, plan.staged)
                        plan.new_subvol_id = d.subvol_show(plan.staged).subvolid
                        plan.dirfd = stack.enter_context(d.open_dir(top))
                        plans.append(plan)
                    journal = d.Journal(f'{completed+1:032x}', fa.uuid, 'prepared', 'now',
                                        [p.journal_entry() for p in plans], tops={fa.uuid:a,fb.uuid:b})
                    journal.commit(a)
                    if mode in ('unwind', 'finalise'):
                        d.activate(plans, journal, a, fix_default=True)
                    child = os.fork()
                    if child == 0:
                        count = [0]
                        def instrument(original):
                            @wraps(original)
                            def wrapped(*args, **kwargs):
                                result = original(*args, **kwargs)
                                count[0] += 1
                                if count[0] == cut:
                                    os.kill(os.getpid(), signal.SIGKILL)
                                return result
                            return wrapped
                        for name in hooks:
                            setattr(d, name, instrument(getattr(d, name)))
                        try:
                            if mode == 'activate':
                                d.activate(plans, journal, a, fix_default=True)
                            elif mode == 'finalise':
                                d.finalise(plans, journal, {fa.uuid:a,fb.uuid:b})
                            else:
                                d._recover_journal(a, fa, d.load_journals(a)[0], abort=True, assume_yes=True)
                        except BaseException:
                            import traceback
                            traceback.print_exc()
                            os._exit(99)
                        os._exit(0)
                    _, status = os.waitpid(child, 0)
                    code = os.waitstatus_to_exitcode(status)
                    assert code in (0, -signal.SIGKILL), (mode, cut, code)
                    journals = d.load_journals(a)
                    if journals:
                        d._recover_journal(a, fa, journals[0], abort=False, assume_yes=True)
                    identities = [d.subvol_show(p.live).subvolid for p in plans]
                    old = [p.target.active_id for p in plans]
                    new = [p.new_subvol_id for p in plans]
                    assert identities in (old, new), (mode, cut, identities, old, new)
                    for plan, sid in zip(plans, identities):
                        assert d.get_default_subvolid(plan.top) == sid, (mode, cut, 'default')
                    assert not d.load_journals(a) and not d.load_journals(b), (mode, cut, 'journal')
                    completed += 1
                    print(f'PASS crash boundary {mode}:{cut}, exit={code}', flush=True)
                    for plan in plans:
                        d.set_default_subvolid(5, plan.top)
                        for path in (plan.live, plan.staged, plan.retired, plan.source):
                            if path.exists():
                                cmd('btrfs', 'subvolume', 'delete', path)
                    if code == 0:
                        break
            else:
                raise AssertionError('crash enumeration did not reach completion')
        print(f'ALL {completed} CRASH-BOUNDARY SCENARIOS PASSED', flush=True)
    finally:
        # Never traverse or delete a filesystem until all our mounts are gone.
        mounts = [e["target"] for e in d.findmnt_entries()
                  if str(e.get("target", "")).startswith(str(base) + "/")]
        for mount in sorted(set(mounts), key=len, reverse=True):
            subprocess.run(["umount", "--", mount], check=True)
        shutil.rmtree(base)
    print("ALL SECOND-PASS BTRFS CHECKS PASSED")


if __name__ == "__main__":
    main()
