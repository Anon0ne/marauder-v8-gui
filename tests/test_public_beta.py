import tkinter as tk
import unittest
from unittest.mock import patch
import sys
import types
import marauder_flash


class PublicBetaTests(unittest.TestCase):
    def test_v8_flash_target_and_offsets(self):
        support = {'bootloader': 'boot.bin', 'partitions': 'part.bin', 'boot_app0': 'ota.bin'}
        args = marauder_flash.flash_args('COM5', 'app.bin', full=True, support=support)
        self.assertEqual(args[:2], ['--chip', 'esp32c5'])
        for value in ['0x2000', '0x8000', '0xe000', '0x10000']:
            self.assertIn(value, args)
        with self.assertRaises(ValueError):
            marauder_flash.flash_args('COM5', 'app.bin', full=True)
        with self.assertRaises(ValueError):
            marauder_flash.flash_args('COM5', 'app.bin', full=True, support=support, boot_offset=0x1000)

    def test_no_heatmap_even_if_private_plugin_is_installed(self):
        from marauder_workspace import WorkspaceGUI
        plugin = types.SimpleNamespace(PLUGIN_API=1)
        with patch.dict(sys.modules, {'marauder_pro': plugin}):
            try:
                app = WorkspaceGUI()
            except tk.TclError as exc:
                self.skipTest(str(exc))
            try:
                app.withdraw()
                self.assertNotIn('heatmap', app._nav_buttons)
                self.assertFalse(hasattr(app, 'open_heatmap'))
                self.assertFalse(hasattr(app, '_build_premium_locked'))
                self.assertIsNone(app.dev)
            finally:
                app._on_close()


if __name__ == '__main__':
    unittest.main()
