# Ideas / backlog

Parked ideas for future releases. Not committed to a timeline.

## GPS WiFi heatmap wardriving page

A live-populating **Tools → Heatmap** page: define a building footprint, wardrive it,
and render a traditional WiFi signal heatmap over GPS coordinates.

**Flow**
1. Define the building: walk the corners and mark POIs (capture `gpsdata` lat/lon per
   corner), or click two corners on the map → draw a rectangle/polygon footprint.
2. Wardrive: start recon; tag each AP observation with the current GPS fix →
   `(bssid, lat, lon, rssi, time)`.
3. Live heatmap: re-interpolate and redraw every few seconds; select a target BSSID or
   show aggregate coverage; color by RSSI.
4. Report: live stats + GeoJSON/KML export + an HTML heatmap report.

**Proposed stack (free, no API key)**
- Map: `tkintermapview` (OpenStreetMap tiles, markers, polygons) — embeds in the Tkinter GUI.
- Interpolation: `numpy` (+ optional `scipy.griddata`) for IDW/kriging.
- Heat overlay on the map, and/or a `Leaflet` + `Leaflet.heat` HTML report.
- GPS source is the device itself (`gpsdata`) — no external GPS API needed. Optional
  Nominatim (free) for address→coordinates search; optional keyed basemap (Mapbox/Esri/
  Google) only if satellite imagery is wanted.

**Difficulty:** moderate. We already have GPS parsing, `wardrive`, POI, and KML export.

**Caveats**
- GPS is unreliable **indoors** (observed `Fix: No / ANTENNA OPEN`). This design suits
  **outdoor coverage / perimeter** mapping. For indoor heatmaps, add a **floor-plan
  overlay + manual "tap your position"** mode instead of GPS.
- Correlating ~1 Hz GPS fixes with faster RSSI samples needs position interpolation while
  moving.
- Adds `tkintermapview` / `numpy` (± `scipy`) deps; grows the Windows EXE; tiles need
  internet (cacheable).
