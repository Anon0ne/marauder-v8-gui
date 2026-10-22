"""Premium feature hook for the community edition.

The community edition contains no premium code and performs no license checks.
Premium features ship in the separately licensed ``marauder_pro`` package, which
verifies its own license before it registers anything. When that package is
absent, premium entries show an upgrade page instead.

Plugin contract: ``marauder_pro.PLUGIN_API == 1`` and
``marauder_pro.open_feature(key, app, page)`` builds the feature (or its license
activation screen) inside ``page``.
"""
import importlib

UPGRADE_URL = "https://github.com/Anon0ne/marauder-v8-gui#premium"
PLUGIN_API = 1
PREMIUM_FEATURES = {
    'heatmap': ('Heatmap mapping',
                'Map WiFi signal strength over GPS coordinates while you wardrive, '
                'with live heatmaps per network, building footprints and '
                'GeoJSON / KML / HTML report export.'),
}


def load_plugin():
    """Return the installed premium package, or None when it is missing or incompatible."""
    try:
        plugin = importlib.import_module('marauder_pro')
    except ImportError:
        return None
    if getattr(plugin, 'PLUGIN_API', None) != PLUGIN_API:
        return None
    return plugin

