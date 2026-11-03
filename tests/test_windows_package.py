import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


class WindowsPackagingTests(unittest.TestCase):
    def test_frozen_assets_and_writable_app_paths_are_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / 'extracted bundle'
            installed = Path(tmp) / 'installed app' / 'MarauderV8-Control.exe'
            with patch.object(sys, 'frozen', True, create=True), patch.object(sys, '_MEIPASS', str(bundle), create=True), patch.object(sys, 'executable', str(installed)):
                paths = runpy.run_path(str(ROOT / 'app_paths.py'))
            self.assertEqual(paths['RESOURCE_DIR'], bundle)
            self.assertEqual(paths['APP_DIR'], installed.parent)

    def test_packaged_smoke_fails_without_bundled_assets(self):
        from marauder_windows_smoke import run
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / 'report.json'
            factory = Mock()
            with patch('app_paths.RESOURCE_DIR', Path(tmp) / 'missing'):
                self.assertEqual(run(factory, report), 1)
            factory.assert_not_called()
            self.assertIn('Bundled default template is missing', json.loads(report.read_text())['error'])

    @unittest.skipUnless(os.name == 'nt' or os.environ.get('DISPLAY'), 'GUI display required')
    def test_offline_smoke_opens_all_pages_without_connecting(self):
        from marauder_windows_smoke import run
        from marauder_workspace import WorkspaceGUI
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / 'report.json'
            self.assertEqual(run(WorkspaceGUI, report), 0, report.read_text())
            data = json.loads(report.read_text())
            self.assertEqual(len(data['pages']), 11)
            self.assertGreater(data['specter_commands'], 0)
            self.assertFalse(data['connected'])
            self.assertFalse(data['autoconnect'])
