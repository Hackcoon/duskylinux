"""Real Btrfs regression tests on two disposable loop images.
Run explicitly: sudo python tests/integration_btrfs.py
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
    base = Path(tempfile.mkdtemp(prefix="dusky-integration-", dir="/var/tmp"))
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
        
        fa=d.filesystem_of(str(a)); fb=d.filesystem_of(str(b))
        print('FILESYSTEMS', fa.uuid, fb.uuid)
        assert d.subvol_show(a).subvolid==5
        assert d.get_default_subvolid(a)==5
        assert d.probe_exchange(a)
        print('PASS metadata and exchange')
        # Current list path behavior on a subvolume mount, including nested subvolumes.
        make(a,'@test/nested')
        mount=Path(base)/'nested-mount';mount.mkdir(exist_ok=True)
        cmd('mount','-o','subvol=@test',fa.mount_source,mount)
        print('LIST from subvolume:',[(x.subvolid,x.path) for x in d.subvol_list(mount)])
        cmd('umount',mount)
        # Successful two-filesystem activation, exact defaults, then explicit unwind.
        plans=[]
        with ExitStack() as stack:
         for idx,(fs,top) in enumerate(((fa,a),(fb,b))):
          live=make(top,f'@live{idx}')
          cmd('btrfs','subvolume','snapshot','-r',live,top/f'@source{idx}')
          old=d.subvol_show(live).subvolid
          d.set_default_subvolid(old,top)
          target=d.RestoreTarget(str(idx), '1', f'/fake{idx}', fs, live.name, old, '')
          plan=d.RestorePlan(target, top, '', live.name, f'@live{idx}_dusky_new_1_20260925T000000Z',f'@live{idx}_to_delete_20260925T000000Z',f'@source{idx}')
          plan.default_before=old
          cmd('btrfs','subvolume','snapshot',plan.source,plan.staged)
          plan.new_subvol_id=d.subvol_show(plan.staged).subvolid
          plan.dirfd=stack.enter_context(d.open_dir(top));plans.append(plan)
         journal=d.Journal('a'*32,fa.uuid,'prepared','now',[p.journal_entry() for p in plans],tops={fa.uuid:a,fb.uuid:b})
         journal.commit(a)
         d.activate(plans,journal,a,fix_default=True)
         for plan in plans:
          assert d.subvol_show(plan.live).subvolid==plan.new_subvol_id
          assert d.get_default_subvolid(plan.top)==plan.new_subvol_id
         assert d.load_journals(b)[0].entries[1].new_subvolid==plans[1].new_subvol_id
         print('PASS two-filesystem activation and replicated journal')
         # Recovery obtains fresh top-level mounts as the real command does.
         d._recover_journal(a,fa,d.load_journals(a)[0],abort=True,assume_yes=True)
         for plan in plans:
          assert d.subvol_show(plan.live).subvolid==plan.target.active_id
          assert d.get_default_subvolid(plan.top)==plan.target.active_id
         assert not d.load_journals(a) and not d.load_journals(b)
         print('PASS two-filesystem unwind and default restoration')
        # Real full and incremental send/receive.
        source=make(a,'@backup')
        cmd('btrfs','subvolume','snapshot','-r',source,a/'@parent')
        backup1=d.backup_subvolume(fa,'@parent',str(b))
        (source/'marker').write_text('changed')
        cmd('btrfs','subvolume','snapshot','-r',source,a/'@child')
        backup2=d.backup_subvolume(fa,'@child',str(b),parent_rel='@parent')
        assert (backup1/'marker').read_text()=='@backup'
        assert (backup2/'marker').read_text()=='changed'
        print('PASS full and incremental send/receive')
        forwarded = d.backup_subvolume(fb, str(backup1.relative_to(b)), str(a))
        assert (forwarded / 'marker').read_text() == '@backup'
        forwarded_child = d.backup_subvolume(fb, str(backup2.relative_to(b)), str(a),
                                              parent_rel=str(backup1.relative_to(b)))
        assert (forwarded_child / 'marker').read_text() == 'changed'
        print('PASS full and incremental forwarding of received subvolumes')
        # Generated service is self-contained in a restored root and accepted by systemd.
        offline=Path(base)/'offline';offline.mkdir(exist_ok=True)
        unit=d.schedule_boot_cleanup(fs_uuid=fa.uuid,subvol_rel='@old_to_delete_20260925T000000Z',subvolid=900,default_subvolid=5,offline_root=offline)
        cmd('systemd-analyze','verify',offline/d.UNIT_DIR_REL/unit)
        print('PASS generated systemd unit validation')
        
        # Backup a writable source to a mounted destination subvolume.
        dest=make(b,'@dest')
        m=Path(base)/'dest-mount';m.mkdir()
        cmd('mount','-o','subvol=@dest',fb.mount_source,m)
        r=d.backup_subvolume(fa,'@backup',str(m))
        assert (r/'marker').read_text()=='changed'
        cmd('btrfs','subvolume','snapshot','-r',a/'@backup',a/'@third')
        r=d.backup_subvolume(fa,'@third',str(m),parent_rel='@parent')
        assert (r/'marker').read_text()=='changed'
        cmd('umount',m)
        print('PASS writable-source and destination-subvolume backups')
        # Interrupt after one exchange, with stale flags, then recover from the replica.
        plans=[]
        for idx,(fs,top) in enumerate(((fa,a),(fb,b))):
         live=make(top,f'@partial{idx}')
         cmd('btrfs','subvolume','snapshot','-r',live,top/f'@partialsource{idx}')
         old=d.subvol_show(live).subvolid
         target=d.RestoreTarget(str(idx),'1',f'/fake{idx}',fs,live.name,old,'')
         plan=d.RestorePlan(target,top,'',live.name,f'@partial{idx}_dusky_new_1_20260925T000000Z',f'@partial{idx}_to_delete_20260925T000000Z',f'@partialsource{idx}')
         plan.default_before=d.get_default_subvolid(top)
         cmd('btrfs','subvolume','snapshot',plan.source,plan.staged)
         plan.new_subvol_id=d.subvol_show(plan.staged).subvolid;plans.append(plan)
        j=d.Journal('b'*32,fa.uuid,'activating','now',[p.journal_entry() for p in plans],tops={fa.uuid:a,fb.uuid:b});j.commit(a)
        d.rename_exchange(plans[0].live,plans[0].staged)
        d._recover_journal(b,fb,d.load_journals(b)[0],abort=False,assume_yes=True)
        for plan in plans: assert d.subvol_show(plan.live).subvolid==plan.new_subvol_id
        assert not d.load_journals(a) and not d.load_journals(b)
        print('PASS stale-journal roll-forward through secondary filesystem')
        # Crash after snapshot creation but before its ID was recorded.
        live=make(a,'@prepared');src=a/'@prepared-source';cmd('btrfs','subvolume','snapshot','-r',live,src)
        e=d.JournalEntry('test','/fake',fa.uuid,'',live.name,'@prepared_dusky_new_1_20260925T000000Z','@prepared_to_delete_20260925T000000Z',src.name,d.subvol_show(live).subvolid)
        j=d.Journal('c'*32,fa.uuid,'prepared','now',[e]);j.commit(a)
        cmd('btrfs','subvolume','snapshot',src,a/e.staged_name)
        d._recover_journal(a,fa,d.load_journals(a)[0],abort=True,assume_yes=True)
        assert not (a/e.staged_name).exists() and live.exists()
        print('PASS interrupted staging without recorded clone ID')
        
        
        # A full restore of a mounted target must defer cleanup into the new root.
        live=make(a,'@full')
        store=make(a,'@store')
        (store/'1').mkdir()
        cmd('btrfs','subvolume','snapshot','-r',live,store/'1/snapshot')
        mount=base/'full-mount';mount.mkdir()
        cmd('mount','-o','subvol=@full',fa.mount_source,mount)
        old_id=d.subvol_show(live).subvolid
        target=d.RestoreTarget('test','1','/',fa,live.name,old_id,store.name)
        plans=d.perform_restore([target],fix_default=True,assume_yes=True)
        retired=plans[0].retired_rel
        unit=plans[0].scheduled_unit
        assert unit and (live/d.UNIT_DIR_REL/unit).is_file()
        assert d.subvol_show(mount).subvolid==old_id
        with patch.object(d,'cancel_boot_cleanup',return_value=True):
            try:
                d.cmd_cleanup_subvol(fa.uuid,retired,expected_id=old_id)
            except d.DuskyError as exc:
                assert 'currently serving' in str(exc)
            else:
                raise AssertionError('cleanup deleted a mounted subvolume')
            cmd('umount',mount)
            try:
                d.cmd_cleanup_subvol(fa.uuid,retired,expected_id=old_id+1000)
            except d.DuskyError as exc:
                assert 'expected' in str(exc)
            else:
                raise AssertionError('cleanup ignored expected identity')
            d.set_default_subvolid(old_id,a)
            try:
                d.cmd_cleanup_subvol(fa.uuid,retired,expected_id=old_id)
            except d.DuskyError as exc:
                assert 'default' in str(exc)
            else:
                raise AssertionError('cleanup deleted the default subvolume')
        print('PASS complete restore, deferred unit, mounted/identity/default cleanup guards')
        # Undo must update a default pointing to the current (post-restore) root.
        new_id=d.subvol_show(live).subvolid
        d.set_default_subvolid(new_id,a)
        with patch.object(d,'btrfs_filesystems',return_value={fa.uuid:(fa,str(a))}), patch.object(d,'cancel_boot_cleanup',return_value=True):
            d.cmd_undo(assume_yes=True)
        assert d.subvol_show(live).subvolid==old_id
        assert d.get_default_subvolid(a)==old_id
        assert not d.load_journals(a)
        print('PASS undo repairs default and removes journal')
        # Verify open transaction guards, then remove the test record explicitly.
        e=d.JournalEntry('test','/fake',fa.uuid,'',live.name,'@unused_dusky_new_1_20260925T000000Z',retired,'@source0',old_id,new_id)
        j=d.Journal('d'*32,fa.uuid,'prepared','now',[e]);j.commit(a)
        try:
            d.cmd_cleanup_subvol(fa.uuid,retired,expected_id=new_id)
        except d.DuskyError as exc:
            assert 'unfinished' in str(exc)
        else:
            raise AssertionError('cleanup ignored unfinished journal')
        j.discard(a)
        print('PASS pending transaction blocks cleanup')
        # Aborting an interrupted undo must preserve both original candidates.
        e = d.JournalEntry('undo', '/fake', fa.uuid, '', live.name, retired,
                           retired, retired, old_id, new_id, old_id)
        j = d.Journal('e'*32, fa.uuid, 'activating', 'now', [e], operation='undo')
        j.commit(a)
        d.rename_exchange(live, a / retired)
        d._recover_journal(a, fa, d.load_journals(a)[0], abort=True, assume_yes=True)
        assert d.subvol_show(live).subvolid == old_id
        assert d.subvol_show(a / retired).subvolid == new_id
        print('PASS interrupted undo preserves both candidates when aborted')
        # A crash during the first replica write can precede the coordinator.
        ea = d.JournalEntry('a', '/fake-a', fa.uuid, '', live.name,
                            '@never_dusky_new_1_20260925T000000Z',
                            '@never_to_delete_20260925T000000Z', '@source0', old_id)
        eb = d.JournalEntry('b', '/fake-b', fb.uuid, '', '@live1',
                            '@never_dusky_new_1_20260925T000000Z',
                            '@never_to_delete_20260925T000000Z', '@source1',
                            d.subvol_show(b / '@live1').subvolid)
        j = d.Journal('f'*32, fa.uuid, 'prepared', 'now', [ea, eb])
        directory = b / d.JOURNAL_DIR_NAME
        directory.mkdir(exist_ok=True)
        d.write_file_durable(directory / ('txn-' + j.txn + '.json'), json.dumps(j.to_json()))
        d._recover_journal(b, fb, d.load_journals(b)[0], abort=False, assume_yes=True)
        assert not d.load_journals(a) and not d.load_journals(b)
        print('PASS recovery after interrupted initial journal replication')
    finally:
        # Never traverse or delete a filesystem until all our mounts are gone.
        mounts = [e["target"] for e in d.findmnt_entries()
                  if str(e.get("target", "")).startswith(str(base) + "/")]
        for mount in sorted(set(mounts), key=len, reverse=True):
            subprocess.run(["umount", "--", mount], check=True)
        shutil.rmtree(base)
    print("ALL BTRFS INTEGRATION CHECKS PASSED")


if __name__ == "__main__":
    main()
