import sys
import tkinter as tk
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import marauder_premium


class PremiumHookTests(unittest.TestCase):
    def test_missing_plugin_is_unavailable(self):
        with patch.dict(sys.modules, {'marauder_pro': None}):
            self.assertIsNone(marauder_premium.load_plugin())

    def test_incompatible_plugin_is_ignored(self):
        with patch.dict(sys.modules, {'marauder_pro': types.SimpleNamespace(PLUGIN_API=99)}):
            self.assertIsNone(marauder_premium.load_plugin())

    def test_compatible_plugin_loads(self):
        plugin = types.SimpleNamespace(PLUGIN_API=marauder_premium.PLUGIN_API)
        with patch.dict(sys.modules, {'marauder_pro': plugin}):
            self.assertIs(marauder_premium.load_plugin(), plugin)

    def _app(self):
        from marauder_workspace import WorkspaceGUI
        try:
            app = WorkspaceGUI()
        except tk.TclError as error:
            self.skipTest(f'GUI display unavailable: {error}')
        app.withdraw()
        app.autoconnect.set(False)
        return app

    def test_heatmap_locked_without_plugin(self):
        with patch.dict(sys.modules, {'marauder_pro': None}):
            app = self._app()
        try:
            app.open_heatmap()
            app.update_idletasks()
            page = app._pages['heatmap']
            texts = [w.cget('text') for w in page.winfo_children() if isinstance(w, tk.ttk.Widget)]
            self.assertIn('Upgrade to Premium', texts)
            with patch('webbrowser.open') as browser:
                next(w for w in page.winfo_children()
                     if isinstance(w, tk.ttk.Button)).invoke()
                browser.assert_called_once_with(marauder_premium.UPGRADE_URL)
        finally:
            app._on_close()

    def test_heatmap_delegates_to_plugin(self):
        plugin = types.SimpleNamespace(PLUGIN_API=marauder_premium.PLUGIN_API, open_feature=Mock())
        with patch.dict(sys.modules, {'marauder_pro': plugin}):
            app = self._app()
        try:
            app.open_heatmap()
            plugin.open_feature.assert_called_once()
            key, owner, page = plugin.open_feature.call_args.args
            self.assertEqual((key, owner), ('heatmap', app))
            self.assertIs(app._pages['heatmap'], page)
        finally:
            app._on_close()


if __name__ == '__main__':
    unittest.main()
