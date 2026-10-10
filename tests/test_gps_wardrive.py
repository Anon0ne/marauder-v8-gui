import unittest
from types import SimpleNamespace
from marauder_gui import MarauderGUI

class Label:
    def configure(self, **kw): self.text = kw.get('text', '')

class GpsWardriveTests(unittest.TestCase):
    def app(self):
        app = SimpleNamespace(dev=True, running=False, _wardrive_status=Label(), _dash_gps=Label(), sent=[], jobs=[])
        app._do_send = lambda cmd: app.sent.append(cmd)
        app.after = lambda ms, fn: app.jobs.append(fn)
        app._dash_parse_gps = lambda: None
        app._dash_wardrive_timeout = lambda: None
        app._dash_poi_timeout = lambda: None
        return app

    def test_read_gps_uses_queries_without_stopping_scan(self):
        app = self.app()
        app.running = True
        MarauderGUI._dash_read_gps(app)
        self.assertEqual(app.sent, ['gps -g ' + f for f in ('fix', 'sat', 'lat', 'lon', 'alt')])
        self.assertTrue(app.running)

    def test_wardrive_does_not_interrupt_current_operation(self):
        app = self.app()
        app.running = True
        MarauderGUI._dash_start_wardrive(app)
        self.assertEqual(app.sent, [])

    def test_poi_requires_wardrive_and_rejects_xml_label(self):
        app = self.app()
        app._poi_label = SimpleNamespace(get=lambda: 'Gate & entry')
        MarauderGUI._dash_mark_poi(app)
        self.assertEqual(app.sent, [])
        app.running = True
        app._last_running_base = 'wardrive'
        MarauderGUI._dash_mark_poi(app)
        self.assertEqual(app.sent, [])
        app._poi_label.get = lambda: 'Gate entrance'
        MarauderGUI._dash_mark_poi(app)
        self.assertEqual(app.sent, ['wardrivepoi Gate entrance'])

    def test_missing_ack_does_not_claim_saved(self):
        app = self.app()
        MarauderGUI._dash_poi_timeout(app)
        self.assertIn('No POI acknowledgement', app._wardrive_status.text)
