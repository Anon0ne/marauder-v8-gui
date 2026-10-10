import io
import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch
import marauder_cloud as cloud
import marauder_secrets as secrets


class CloudTests(unittest.TestCase):
    def test_consent_required_before_network(self):
        with patch.object(cloud.urllib.request, 'build_opener') as opener:
            with self.assertRaises(ValueError):
                cloud.chat([], 'OpenRouter Free', 'openrouter/free', 'dummy')
            opener.assert_not_called()

    def test_paid_model_rejected(self):
        with self.assertRaises(ValueError):
            cloud.validate('OpenRouter Free', 'paid/model', 'dummy')

    def test_aggregates_exclude_identifiers(self):
        output = cloud.aggregate_context({'ap': {'0': {'ssid': 'PrivateName', 'bssid': 'aa:bb:cc:dd:ee:ff', 'lat': 35, 'channel': '6', 'rssi': '-42'}}})
        self.assertIn('ap count: 1', output)
        self.assertNotIn('PrivateName', output)
        self.assertNotIn('aa:bb', output)

    def test_mocked_success_and_invalid_response(self):
        opener = Mock()
        for payload, valid in [({'choices': [{'message': {'content': 'Ready'}}]}, True), ([], False)]:
            opener.open.return_value = io.BytesIO(json.dumps(payload).encode())
            with patch.object(cloud.urllib.request, 'build_opener', return_value=opener):
                if valid:
                    self.assertEqual(cloud.chat([], 'OpenRouter Free', 'openrouter/free', 'dummy', consent=True), 'Ready')
                else:
                    with self.assertRaises(RuntimeError):
                        cloud.chat([], 'OpenRouter Free', 'openrouter/free', 'dummy', consent=True)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, cloud.PROVIDERS['OpenRouter Free'][0])

    @unittest.skipUnless(os.name == 'nt', 'Windows DPAPI')
    def test_dpapi_roundtrip_without_plaintext_storage(self):
        with tempfile.TemporaryDirectory() as folder:
            secrets.save(folder, 'OpenRouter Free', 'dummy-test-key')
            self.assertNotIn(b'dummy-test-key', secrets.key_path(folder, 'OpenRouter Free').read_bytes())
            self.assertEqual(secrets.load(folder, 'OpenRouter Free'), 'dummy-test-key')
            secrets.forget(folder, 'OpenRouter Free')
            self.assertEqual(secrets.load(folder, 'OpenRouter Free'), '')
