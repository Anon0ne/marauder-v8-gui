import hashlib
import io
import json
import struct
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import serial
import marauder_ai
import marauder_flash
import marauder_pcap
import marauder_sessions
from marauder import Marauder
from marauder_gui import MarauderGUI, spreadsheet_cell


class ReliabilityTests(unittest.TestCase):
    def test_diagnostic_report_never_dispatches_model_commands(self):
        fake = SimpleNamespace(
            _ai_ready=True, _ai_busy=False, _ai_verified=('Ollama', 'test:latest'),
            _ai_model=SimpleNamespace(get=lambda: 'test:latest'),
            _ai_backend=SimpleNamespace(get=lambda: 'Ollama'),
            _ai_context=lambda: 'Test observations',
            _ai_generate=lambda *args: 'RUN: attack -t deauth',
            _ai_out=Mock(), _ai_dispatch=Mock(), _do_send=Mock())
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / 'diagnostic.md'
            with patch('marauder_gui.filedialog.asksaveasfilename', return_value=str(report)), \
                    patch('marauder_gui.threading.Thread') as worker:
                MarauderGUI._ai_report(fake)
                worker.call_args.kwargs['target']()
            self.assertIn('Model-generated analysis', report.read_text())
        fake._ai_dispatch.assert_not_called()
        fake._do_send.assert_not_called()

    def test_csv_formula_names_are_literal(self):
        for name in ['=HYPERLINK("https://example.com")', '+cmd', '@SUM(1)', '  =1+1', '-1+2']:
            self.assertTrue(spreadsheet_cell(name).startswith("'"))
        self.assertEqual(spreadsheet_cell('Normal network'), 'Normal network')
        self.assertEqual(spreadsheet_cell(-42), -42)

    def test_constructor_has_finite_write_timeout(self):
        with patch('marauder.serial.Serial') as factory, patch('marauder.time.sleep'):
            Marauder('COM99')
        self.assertEqual(factory.call_args.kwargs['write_timeout'], 1.0)

    def test_partial_write_does_not_retry_or_flush(self):
        device = Marauder.__new__(Marauder)
        device.ser = Mock()
        device.ser.write.return_value = 2
        with self.assertRaises(serial.SerialTimeoutException):
            device.send('info')
        device.ser.write.assert_called_once()
        device.ser.flush.assert_not_called()

    def test_leading_control_character_rejected(self):
        device = Marauder.__new__(Marauder)
        device.ser = Mock()
        with self.assertRaises(ValueError):
            device.send('\ninfo')
        device.ser.write.assert_not_called()

    def test_ble_active_scan_excluded_from_autonomy(self):
        self.assertTrue(marauder_ai.is_active('recon ble'))
        self.assertFalse(marauder_ai.is_passive('recon ble'))

    def test_model_tags_must_match(self):
        self.assertFalse(marauder_ai.has_model(['llama3.1:70b'], 'llama3.1:8b'))
        self.assertTrue(marauder_ai.has_model(['llama3.1:latest'], 'llama3.1'))

    def test_local_ai_rejects_remote_host_before_request(self):
        with patch('marauder_ai.urllib.request.build_opener') as opener:
            with self.assertRaises(ValueError):
                marauder_ai.chat([], host='https://example.com')
            opener.assert_not_called()

    def test_local_ai_uses_loopback_ip_literals_only(self):
        self.assertEqual(marauder_ai.urlparse(marauder_ai.OLLAMA_HOST).hostname, '127.0.0.1')
        with patch('marauder_ai.urllib.request.build_opener') as opener:
            for host in ('http://localhost:11434', 'http://localhost.example:11434'):
                with self.assertRaises(ValueError):
                    marauder_ai.chat([], host=host)
            opener.assert_not_called()

    def test_duplicate_run_lines_dispatch_once(self):
        self.assertEqual(marauder_ai.extract_run_commands('RUN: info\nRUN: info'), ['info'])

    def test_replay_only_accepts_rx_objects(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'session.jsonl'
            items = [[], None, 'text', {'direction': 'tx', 'data': 'attack'},
                     {'direction': 'rx', 'data': 'observations\n'}, {'direction': 'rx', 'data': 123}]
            path.write_text('\n'.join(json.dumps(x) for x in items) + '\ninvalid\n')
            self.assertEqual(list(marauder_sessions.received_chunks(path)), ['observations\n'])

    def test_replay_rejects_oversized_line(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'session.jsonl'
            path.write_bytes(b'x' * 1025)
            with patch.object(marauder_sessions, 'MAX_LINE_BYTES', 1024):
                with self.assertRaises(ValueError):
                    list(marauder_sessions.received_chunks(path))

    def test_recording_failure_does_not_break_receiver(self):
        fp = Mock()
        fp.write.side_effect = OSError('disk full')
        fake = SimpleNamespace(_record_fp=fp, _emit=Mock())
        MarauderGUI._record_event(fake, 'rx', 'radio observation')
        self.assertIsNone(fake._record_fp)
        fake._emit.assert_called_once()

    def test_reader_error_is_queued_not_handled_on_worker(self):
        import queue
        device = Mock()
        device.read_available.side_effect = OSError('unplugged')
        fake = SimpleNamespace(dev=device, reader_stop=threading.Event(),
                               _ui_queue=queue.Queue(), _serial_failed=Mock())
        MarauderGUI._reader_loop(fake)
        fake._serial_failed.assert_not_called()
        fake._ui_queue.get_nowait()()
        fake._serial_failed.assert_called_once_with(device, 'unplugged')

    def test_asset_selection_requires_exact_board_suffix(self):
        self.assertIsNone(marauder_flash.pick_asset([{'name': 'something_v8_wrong.bin'}], 'v8'))
        with self.assertRaises(ValueError):
            marauder_flash.safe_asset_path('.', '../firmware.bin')

    def test_incomplete_download_preserves_existing_image(self):
        response = io.BytesIO(b'short')
        response.headers = {'Content-Length': '9'}
        response.geturl = lambda: 'https://github.com/owner/repo/releases/download/v1/app_v8.bin'
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'firmware.bin'
            path.write_bytes(b'original')
            with patch('marauder_flash.urllib.request.urlopen', return_value=response):
                with self.assertRaises(ValueError):
                    marauder_flash.download_asset(response.geturl(), path, expected_size=9,
                                                  expected_sha256='0' * 64)
            self.assertEqual(path.read_bytes(), b'original')
            self.assertEqual(list(Path(folder).glob('*.part')), [])

    def _fake_download(self, payload):
        response = io.BytesIO(payload)
        response.headers = {'Content-Length': str(len(payload))}
        response.geturl = lambda: 'https://github.com/owner/repo/releases/download/v1/app_v8.bin'
        return response

    def _download(self, payload, sha256):
        response = self._fake_download(payload)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / 'firmware.bin'
        path.write_bytes(b'original')
        with patch('marauder_flash.urllib.request.urlopen', return_value=response):
            try:
                marauder_flash.download_asset(response.geturl(), path, expected_size=len(payload),
                                              expected_sha256=sha256)
            finally:
                self.assertEqual(list(Path(folder.name).glob('*.part')), [])
        return path

    def test_download_accepts_image_matching_published_digest(self):
        payload = b'\xe9' + b'firmware' * 8
        path = self._download(payload, hashlib.sha256(payload).hexdigest().upper())
        self.assertEqual(path.read_bytes(), payload)

    def test_download_rejects_digest_mismatch(self):
        payload = b'\xe9' + b'tampered' * 8
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            self._download(payload, hashlib.sha256(b'genuine').hexdigest())

    def test_download_requires_published_digest(self):
        for missing in (None, '', 'md5:abc'):
            with self.assertRaisesRegex(ValueError, 'digest'):
                self._download(b'\xe9data', missing)

    def test_download_rejects_non_esp_image(self):
        payload = b'<html>not firmware</html>'
        with self.assertRaisesRegex(ValueError, 'ESP firmware'):
            self._download(payload, hashlib.sha256(payload).hexdigest())

    def test_release_digest_parsing(self):
        good = 'sha256:' + 'Ab' * 32
        self.assertEqual(marauder_flash.parse_sha256_digest(good), 'ab' * 32)
        for bad in (None, '', 'sha256:xyz', 'sha512:' + 'a' * 64, 'sha256:' + 'a' * 63):
            self.assertIsNone(marauder_flash.parse_sha256_digest(bad))

    def test_pcap_rejects_hostile_snaplen(self):
        header = struct.pack('<IHHIIII', 0xa1b2c3d4, 2, 4, 0, 0, 0xffffffff, 105)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'hostile.pcap'
            path.write_bytes(header)
            with self.assertRaises(marauder_pcap.PcapError):
                marauder_pcap.summarize(path)

    def test_zero_epoch_pcap_has_correct_duration(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'valid.pcap'
            header = struct.pack('<IHHIIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 105)
            path.write_bytes(header + struct.pack('<IIII', 0, 0, 1, 1) + b'a' +
                             struct.pack('<IIII', 1, 0, 1, 1) + b'b')
            self.assertEqual(marauder_pcap.summarize(path)['duration_s'], 1.0)

    def test_pcap_and_replay_reject_non_regular_files(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(marauder_pcap.PcapError):
                marauder_pcap.summarize(folder)
            with self.assertRaises(ValueError):
                list(marauder_sessions.received_chunks(folder))
            with self.assertRaises(OSError):
                list(marauder_sessions.received_chunks(Path(folder) / 'missing.jsonl'))


if __name__ == '__main__':
    unittest.main()
