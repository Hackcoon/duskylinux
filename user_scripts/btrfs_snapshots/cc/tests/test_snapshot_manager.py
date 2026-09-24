"""Regression tests; no root privileges or real snapshot changes required."""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'dusky_snapshot_manager.py'
spec = importlib.util.spec_from_file_location('dusky', SCRIPT)
d = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = d
spec.loader.exec_module(d)

class RegressionTests(unittest.TestCase):
    def test_fstab_and_boot_options(self):
        for value in ('subvolid=256', 'Options=subvolid=256',
                      'UUID=x / btrfs subvolid=256 0 0', 'rootflags=subvolid=256,rw'):
            self.assertEqual(d.subvolid_from_options(value), 256)
        self.assertEqual(d.subvol_from_options('UUID=x / btrfs subvol=/@ 0 0'), '@')

    def test_default_command_has_no_unsupported_separator(self):
        with patch.object(d, 'run', return_value=d.Proc([], 0, 'ID 5 (FS_TREE)\n', '')) as run:
            self.assertEqual(d.get_default_subvolid('/mnt'), 5)
            self.assertEqual(run.call_args.args, ('btrfs', 'subvolume', 'get-default', '/mnt'))

    def test_sync_errors_propagate(self):
        with patch.object(d.subprocess, 'run') as run:
            run.return_value.returncode = 1
            run.return_value.stdout = ''
            run.return_value.stderr = 'I/O error'
            with self.assertRaises(d.DuskyError):
                d.btrfs_sync('/mnt')

    def test_mount_query_failure_is_not_idle(self):
        with patch.object(d, 'run', return_value=d.Proc([], 1, '', 'permission denied')):
            with self.assertRaises(d.DuskyError):
                d.live_mount_of_subvolid('x', 256)

    def test_bind_mount_is_busy(self):
        entry = dict(fstype='btrfs', uuid='x', target='/bind', options='rw,subvolid=256')
        with patch.object(d, 'findmnt_entries', return_value=[entry]):
            self.assertEqual(d.live_mount_of_subvolid('x', 256), '/bind')

    def test_short_writes(self):
        original = d.os.write
        with tempfile.TemporaryDirectory() as tmp, patch.object(d.os, 'write', side_effect=lambda fd, data: original(fd, data[:3])):
            target = Path(tmp) / 'journal'
            d.write_file_durable(target, 'abcdefghij')
            self.assertEqual(target.read_text(), 'abcdefghij')

    def test_corrupt_journal_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / d.JOURNAL_DIR_NAME
            directory.mkdir()
            (directory / 'txn-test.json').write_text('{broken')
            with self.assertRaises(d.DuskyError):
                d.load_journals(Path(tmp))

    def test_missing_tagged_pair_does_not_substitute(self):
        left = dict(id='1', raw_date='2026-01-01 00:00:00', epoch=1,
                    dead=False, description='test', type='single', userdata_dict={'dusky_pair': 'one'})
        right = left | dict(id='2', userdata_dict={})
        with patch.object(d, 'snapshot_rows', side_effect=[[left], [right]]):
            with self.assertRaises(d.DuskyError):
                d.find_pair('root', 'home', left_id_hint='1')

    def test_recovery_rejects_unrelated_identity(self):
        entry = d.JournalEntry('root', '/', 'x', '', '@', '@stage', '@old', 'source', 256, 257)
        info = d.SubvolInfo(999, '@', '', '', '', 0, False)
        with patch.object(d.os.path, 'lexists', return_value=True), patch.object(d, 'subvol_show', return_value=info):
            with self.assertRaises(d.DuskyError):
                d._inspect_entry(entry, Path('/mnt'))

    def test_receive_cleanup_never_erases_files_on_delete_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            staging = Path(tmp) / 'staging'; staging.mkdir()
            item = staging / 'subvol'; item.mkdir()
            (item / 'keep').write_text('data')
            info = d.SubvolInfo(256, 'subvol', '', '', '', 0, False)
            with patch.object(d, 'run', return_value=d.Proc([], 1, '', 'busy')), \
                 patch.object(d, 'get_default_subvolid', return_value=5), \
                 patch.object(d, 'subvol_show', return_value=info), \
                 patch.object(d, 'live_mount_of_subvolid', return_value=None):
                self.assertFalse(d._purge_staging(staging, fs_uuid='test'))
            self.assertEqual((item / 'keep').read_text(), 'data')

class SecondPassTests(unittest.TestCase):
    def test_finalised_replica_still_blocks_changes(self):
        journal = d.Journal('txn', 'fs', 'finalised', '', [])
        with patch.object(d, 'load_journals', return_value=[journal]):
            with self.assertRaises(d.DuskyError):
                d.assert_no_open_transactions(Path('/mnt'))

    def test_restore_rejects_retired_live_mount(self):
        fs = d.Filesystem('x', '')
        with patch.object(d, 'snapper_config_subvolume', return_value='/'), \
             patch.object(d, 'is_mountpoint', return_value=True), \
             patch.object(d, 'filesystem_of', return_value=fs), \
             patch.object(d, 'active_subvol', side_effect=[('@_to_delete_20260925T000000Z', 256), ('@snapshots', 258)]):
            with self.assertRaises(d.DuskyError):
                d.resolve_target('root', '1')

    def test_timestamp_does_not_override_description(self):
        left = dict(id='1', raw_date='now', epoch=1, dead=False,
                    description='wanted', type='single', userdata_dict={})
        right = left | dict(id='2', description='unrelated')
        with patch.object(d, 'snapshot_rows', side_effect=[[left], [right]]):
            with self.assertRaises(d.DuskyError):
                d.find_pair('root', 'home', left_id_hint='1')

    def test_heuristic_does_not_steal_another_tagged_pair(self):
        left = dict(id='1', raw_date='now', epoch=1, dead=False,
                    description='same', type='single', userdata_dict={})
        right = left | dict(id='2', userdata_dict={'dusky_pair':'another'})
        with patch.object(d, 'snapshot_rows', side_effect=[[left], [right]]):
            with self.assertRaises(d.DuskyError):
                d.find_pair('root', 'home', left_id_hint='1')

    def test_mount_labels_are_filesystem_qualified(self):
        entries = [dict(fstype='btrfs',uuid=uuid,target=target,options='subvol=/@')
                   for uuid,target in [('one','/'),('two','/mnt/other')]]
        d.invalidate_cache()
        with patch.object(d,'findmnt_entries',return_value=entries):
            mapping=d.mounted_subvol_paths()
            self.assertEqual(mapping[('one','@')], '/')
            self.assertEqual(mapping[('two','@')], '/mnt/other')
        d.invalidate_cache()

    def test_sweep_does_not_touch_other_filesystem_before_journal_check(self):
        from contextlib import nullcontext
        with tempfile.TemporaryDirectory() as tmp:
            top = Path(tmp)
            (top / '.btrfs_recv_test').mkdir()
            filesystems = {'a': (d.Filesystem('a', ''), '/a'),
                           'b': (d.Filesystem('b', ''), '/b')}
            entry = dict(fstype='btrfs', uuid='b', target=str(top))
            checks = iter([None, d.DuskyError('unfinished')])
            def check(_top):
                error = next(checks)
                if error:
                    raise error
            with patch.object(d,'dusky_lock',side_effect=nullcontext), \
                 patch.object(d,'top_level',side_effect=lambda *a,**kw:nullcontext(top)), \
                 patch.object(d,'btrfs_filesystems',return_value=filesystems), \
                 patch.object(d,'assert_no_open_transactions',side_effect=check), \
                 patch.object(d,'subvol_list',return_value=[]), \
                 patch.object(d,'btrfs_sync'), \
                 patch.object(d,'findmnt_entries',return_value=[entry]), \
                 patch.object(d,'_purge_staging') as purge:
                with self.assertRaises(d.DuskyError):
                    d.sweep_orphans(apply=True)
                purge.assert_not_called()

    def test_pair_delete_validates_both_ids_before_deleting(self):
        from contextlib import nullcontext
        with patch.object(d,'dusky_lock',side_effect=nullcontext), \
             patch.object(d,'snapshot_rows',side_effect=[[{'id':'1'}], []]), \
             patch.object(d,'cmd_delete') as delete:
            with self.assertRaises(d.DuskyError):
                d.cmd_delete_pair('left','1','right','2')
            delete.assert_not_called()

if __name__ == '__main__':
    unittest.main()
