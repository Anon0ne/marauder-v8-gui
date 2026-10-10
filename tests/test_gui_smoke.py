import sys
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from marauder_workspace import WorkspaceGUI


class GuiSmokeTests(unittest.TestCase):
    def test_embedded_pages_live_parser_and_logged_survey(self):
        try:
            app = WorkspaceGUI()
        except tk.TclError as error:
            self.skipTest(f'GUI display unavailable: {error}')
        app.withdraw()
        app.autoconnect.set(False)
        try:
            for open_page in [app.open_ai_dialog, app.open_ble_devices,
                              app.open_sd_browser, app.open_dashboard,
                              app.open_survey, app.open_firmware_dialog,
                              app.open_pcap_dialog]:
                open_page()
                app.update_idletasks()
            self.assertFalse(any(isinstance(child, tk.Toplevel) for child in app.winfo_children()))
            app._ingest('-42 Ch: 6 00:11:22:33:44:55 ESSID: Test-Lab 31 00\n')
            app._ingest('11: sta: 02:11:22:33:44:66 -> ap: 00:11:22:33:44:55\n')
            self.assertTrue(any(row.get('bssid') == '02:11:22:33:44:66' for row in app._lists['sta'].values()))
            app._ingest('11: ap: 00:11:22:33:44:55 -> sta: 33:33:00:00:00:01\n')
            self.assertEqual(len(app._lists['sta']), 1)
            app.dev = Mock()
            with tempfile.TemporaryDirectory() as folder:
                app._logs_dir = lambda: folder
                app._survey_toggle()
                self.assertIsNotNone(app._record_fp)
                app._ingest('-40 Ch: 6 00:11:22:33:44:55 ESSID: Test-Lab 31 00\n')
                app._survey_toggle()
                app.dev.send.assert_any_call('recon wifi')
                app.dev.send.assert_any_call('stopscan')
                self.assertEqual(app.dev.send.call_count, 2)
                self.assertIsNone(app._record_fp)
                recording = next(Path(folder).glob('*.jsonl')).read_text()
                self.assertIn('Test-Lab', recording)
                self.assertIn('"direction": "tx"', recording)
        finally:
            app._on_close()


if __name__ == '__main__':
    unittest.main()
