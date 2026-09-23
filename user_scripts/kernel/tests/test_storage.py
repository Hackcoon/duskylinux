"""Small real-rsync fixtures; no system mounts, dependencies or kernel builds."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kernel_storage as s


def run(argv):
    subprocess.run(argv, check=True, capture_output=True)


class StorageTests(unittest.TestCase):
    def settings(self, root):
        disk = root / 'disk'
        return dict(persistent_dir=disk, packages_dir=disk / 'packages',
                    thinlto_dir=disk / 'thinlto-cache', ccache_dir=disk / 'ccache',
                    zram_dir=root / 'ram', ram_reserve_gib=8)

    def test_restore_save_and_reboot_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); cfg = self.settings(root)
            obj = cfg['persistent_dir'] / 'src/linux/kernel/test.o'
            obj.parent.mkdir(parents=True); obj.write_bytes(b'previous compiled object')
            timestamp = obj.stat().st_mtime_ns
            with patch.object(s, 'ram_mount', side_effect=lambda p: root / 'ram' in p.parents):
                with s.ram_workspace(cfg, run, lambda _: None) as ram:
                    restored = ram / 'src/linux/kernel/test.o'
                    self.assertEqual(restored.stat().st_mtime_ns, timestamp)
                    self.assertEqual(restored.read_bytes(), obj.read_bytes())
                    (ram / 'ccache/result').write_bytes(b'cached compile')
                    restored.write_bytes(b'new object')
                self.assertEqual(obj.read_bytes(), b'new object')
                self.assertEqual((cfg['ccache_dir'] / 'result').read_bytes(), b'cached compile')
                import shutil
                shutil.rmtree(root / 'ram')
                with s.ram_workspace(cfg, run, lambda _: None) as ram:
                    self.assertEqual((ram / 'src/linux/kernel/test.o').read_bytes(), b'new object')
                    self.assertEqual((ram / 'ccache/result').read_bytes(), b'cached compile')

    def test_failure_still_checkpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); cfg = self.settings(root)
            with patch.object(s, 'ram_mount', side_effect=lambda p: root / 'ram' in p.parents):
                with self.assertRaises(KeyboardInterrupt):
                    with s.ram_workspace(cfg, run, lambda _: None) as ram:
                        (ram / 'src/partial.o').write_bytes(b'reusable')
                        raise KeyboardInterrupt()
            self.assertEqual((cfg['persistent_dir'] / 'src/partial.o').read_bytes(), b'reusable')

    def test_failed_save_protects_unsaved_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); cfg = self.settings(root)
            with patch.object(s, 'ram_mount', side_effect=lambda p: root / 'ram' in p.parents):
                with self.assertRaises(OSError):
                    def broken_run(argv):
                        if str(root / 'ram') in argv[-2]:
                            raise OSError('disk full')
                        run(argv)
                    with s.ram_workspace(cfg, broken_run, lambda _: None):
                        pass
                with self.assertRaisesRegex(s.StorageError, 'Unsaved'):
                    with s.ram_workspace(cfg, run, lambda _: None):
                        self.fail('Must not overwrite unsaved RAM data')

    def test_missing_mount_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(s, 'ram_mount', return_value=False):
            with self.assertRaisesRegex(s.StorageError, 'not on a mounted'):
                with s.ram_workspace(self.settings(Path(tmp)), run, lambda _: None):
                    self.fail()

    def test_volatile_package_destination_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); cfg = self.settings(root); cfg['packages_dir'] = root / 'ram/packages'
            with patch.object(s, 'ram_mount', side_effect=lambda p: root / 'ram' in p.parents):
                with self.assertRaisesRegex(s.StorageError, 'Package destination'):
                    with s.ram_workspace(cfg, run, lambda _: None):
                        self.fail()

    def test_build_dir_override_updates_default_cache_paths(self):
        template = Path(__file__).resolve().parents[1] / 'kernel_settings.toml'
        with patch.dict('os.environ', {}, clear=True):
            cfg = s.load_settings(template, Path('/old/cache'), Path('/new/build'))
        self.assertEqual(cfg['packages_dir'], Path('/new/build/packages'))
        self.assertEqual(cfg['thinlto_dir'], Path('/new/build/thinlto-cache'))

    def test_settings_validation_and_defaults(self):
        template = Path(__file__).resolve().parents[1] / 'kernel_settings.toml'
        with patch.dict('os.environ', {}, clear=True):
            cfg = s.load_settings(template, Path('/disk/cache'))
            self.assertEqual(cfg['packages_dir'], Path('/disk/cache/dusky-kernel/packages'))
            self.assertEqual(cfg['persistent_dir'], Path('/disk/cache/dusky-kernel'))
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / 'bad.toml'
            bad.write_text(template.read_text().replace('ram_reserve_gib = 8', 'ram_reserve_gib = true'))
            with self.assertRaises(s.StorageError):
                s.load_settings(bad, Path(tmp))
