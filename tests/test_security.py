import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import marauder_ai
from marauder import Marauder
from marauder_gui import MarauderGUI, redact


class SecurityTests(unittest.TestCase):
    def test_unknown_and_active_commands_fail_closed(self):
        for command in ['recon ble', 'reboot', 'join -a 0', 'select -a 1', 'attack -t deauth',
                        'listwhatever', 'recon wifi\nattack -t deauth',
                        'recon wifi -d', 'channel -s 6', 'list -a\x7f']:
            with self.subTest(command=command):
                self.assertFalse(marauder_ai.is_passive(command))

    def test_expected_passive_commands_remain_allowed(self):
        for command in ['recon wifi', 'recon stop', 'stopscan', 'list -a']:
            self.assertTrue(marauder_ai.is_passive(command))

    def test_dispatch_does_not_autorun_unknown_commands(self):
        sent = []
        fake = SimpleNamespace(_ai_win=SimpleNamespace(winfo_exists=lambda: True,
                              after=lambda delay, callback: callback()),
                              _ai_autorun=SimpleNamespace(get=lambda: True), dev=object(),
                              raw_var=SimpleNamespace(set=lambda value: None),
                              _do_send=lambda command: sent.append(command),
                              _ai_out=lambda text: None)
        MarauderGUI._ai_dispatch_main(fake, 'reboot')
        self.assertEqual(sent, [])
        MarauderGUI._ai_dispatch_main(fake, 'recon wifi')
        self.assertEqual(sent, ['recon wifi'])

    def test_invalid_ai_output_never_changes_raw_box(self):
        raw = Mock()
        fake = SimpleNamespace(raw_var=raw, _ai_out=Mock())
        for command in ['esptool --port COM4 --before nonsense', 'reboot',
                        'attack -t deauth', 'recon wifi\nstopscan']:
            MarauderGUI._ai_dispatch_main(fake, command)
        raw.set.assert_not_called()

    def test_survey_starts_once_and_stop_cancels_timer(self):
        sent, timers = [], {}
        fake = SimpleNamespace(_survey_on=False, _ai_survey_on=False, dev=object(), running=False,
                               _survey_btn=Mock(), _survey_merge=Mock(),
                               _do_send=lambda command, **kw: sent.append(command),
                               after=lambda delay, cb: timers.setdefault('job', cb) and 'job',
                               after_cancel=lambda job: timers.pop(job, None))
        fake._finish_survey_recording = lambda: None
        fake._survey_step = lambda: MarauderGUI._survey_step(fake)
        MarauderGUI._survey_toggle(fake)
        for _ in range(4):
            timers['job']()
        self.assertEqual(sent, ['recon wifi'])
        MarauderGUI._survey_toggle(fake)
        self.assertEqual(sent, ['recon wifi', 'stopscan'])
        self.assertEqual(timers, {})
        fake._survey_step()
        self.assertEqual(sent, ['recon wifi', 'stopscan'])

    def test_serial_injection_rejected_before_write(self):
        transport = Marauder.__new__(Marauder)
        transport.ser = Mock()
        for command in ['help\nreboot', 'help\x00', 'help\x7f', 'a' * 4097]:
            with self.assertRaises(ValueError):
                transport.send(command)
        transport.ser.write.assert_not_called()

    def test_quoted_password_is_fully_redacted(self):
        for secret in ['simple-secret', '"two word secret"', "'two word secret'"]:
            shown = redact('join -a 0 -p ' + secret)
            self.assertEqual(shown, 'join -a 0 -p ***')

    def test_continuous_serial_input_has_bounded_read(self):
        transport = Marauder.__new__(Marauder)
        transport.ser = SimpleNamespace(in_waiting=1000000, read=lambda count: b'x' * count)
        self.assertLessEqual(len(transport.read_available()), 65536)


if __name__ == '__main__':
    unittest.main()
