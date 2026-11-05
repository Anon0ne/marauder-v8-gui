"""Offline packaged-app verification; never connects to a radio or starts a job."""
import json
from pathlib import Path
import sys
import traceback


def run(app_factory, report_path):
    result = {'result': 'fail', 'frozen': bool(getattr(sys, 'frozen', False)), 'pages': []}
    app = None
    try:
        from app_paths import RESOURCE_DIR
        import esptool
        import serial
        from marauder_commands import CATALOG
        asset = RESOURCE_DIR / 'portals/default/index.html'
        if not asset.is_file():
            raise RuntimeError('Bundled default template is missing')
        result['bundled_default_template'] = True
        result['esptool_version'] = esptool.__version__
        result['serial_version'] = serial.__version__
        result['specter_commands'] = sum(len(commands) for title, groups in CATALOG if title == 'Specter' for _, commands in groups)
        if not result['specter_commands']:
            raise RuntimeError('Specter catalog missing')
        app = app_factory()
        app.autoconnect.set(False)
        app.withdraw()
        callback_errors = []
        app.report_callback_exception = lambda *error: callback_errors.append(str(error[1]))
        for name in ('_show_catalog', 'open_specter', 'open_sd_browser', 'open_portal_templates',
                     'open_ble_devices', 'open_dashboard', 'open_survey', 'open_firmware_dialog',
                     'open_pcap_dialog', 'open_ai_dialog', 'open_heatmap'):
            getattr(app, name)()
            app.update_idletasks()
            app.update()
            result['pages'].append(name)
        if app.dev is not None or app.autoconnect.get():
            raise RuntimeError('Smoke test connected or enabled autoconnect')
        if callback_errors:
            raise RuntimeError('; '.join(callback_errors))
        result['autoconnect'] = False
        result['connected'] = False
        result['pro_plugin_loaded'] = app._premium is not None
        result['result'] = 'pass'
    except Exception:
        result['error'] = traceback.format_exc()
    finally:
        if app is not None:
            try:
                app._on_close()
            except Exception:
                result['result'] = 'fail'
                result['close_error'] = traceback.format_exc()
        output = Path(report_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    return 0 if result['result'] == 'pass' else 1
