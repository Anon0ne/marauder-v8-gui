# GPS and wardrive troubleshooting

The dashboard now sends `gps -g fix`, `gps -g sat`, `gps -g lat`, `gps -g lon`, and `gps -g alt`. The toolbox GPS Query uses the same firmware syntax. These queries do not switch scan mode. `gpsdata` and `gps -t` start GPS display/tracking modes and can interrupt RF scans; use them deliberately.

Start Wardrive sends `wardrive` once and requires the current operation to be stopped first. Wardrive is a manual operation, excluded from autonomous passive analysis. Firmware GPS support and successful GPS module detection at startup are required. An undetected module can make the command silently return. Check for `GPS Not Found` at boot, GPS wiring and baud rate, and the installed firmware target. A missing satellite fix differs from a missing module: a supported status query should still report Fix: No.

Mark POI sends `wardrivepoi <label>` to mark the device's current GPS position. An empty label lets firmware assign POI N. Firmware requires active wardrive, a GPS fix, GPS/SD support, and an opened POI file. Labels are limited to 80 characters and exclude controls and XML markup characters to protect the GPX structure.

Wardrive observations are logged to the device SD card when available. POIs use `/wardrive_poi_*.gpx`; stop wardrive before removing the card. The GUI displays firmware acknowledgement separately from storage verification: the inspected firmware prints POI tagged even if its subsequent SD open fails, so inspect the GPX file to confirm persistence.

Firmware reviewed: official ESP32 Marauder commit d3ceb28afeda1196ca27c13adeaa69ada52383f3, CommandLine.cpp and WiFiScan.cpp. Physical GPS, SD writes and wardrive execution remain unverified on the user's device. These source changes require a rebuilt executable to affect an existing desktop installation.
