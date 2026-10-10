"""
marauder_commands.py — the command catalog driving the GUI.

Built from the live `help` dump of THIS device's firmware (ESP32 Marauder V8
fork, CH340). If you flash a different build and the syntax changes, edit here.

This is the ONLY file you edit to add/fix commands. Each command declares:
  name   : label shown in the tree
  base   : the literal command token(s) sent to the firmware
  help   : explanation shown under the parameter box
  params : optional list of parameter specs (see Param below)

Param kinds:
  "bool"   -> checkbox; when checked, appends the flag (no value)
  "text"   -> free text; appends `flag value` (or just `value` if flag is None)
  "int"    -> digits; appends `flag value`
  "choice" -> dropdown; appends `flag value` (or just `value` if flag is None)
"""


def P(label, flag=None, kind="text", choices=None, placeholder="", default="",
      help="", source="", multi=False):
    # source: "ap"/"sta"/"ssid" shows a double-click picker from that scanned list;
    #         "auto" follows this command's -a/-s/-c dropdown. multi=True appends
    #         picked indices (comma-separated) instead of replacing.
    return {
        "label": label,
        "flag": flag,
        "kind": kind,
        "choices": choices or [],
        "placeholder": placeholder,
        "default": default,
        "help": help,
        "source": source,
        "multi": multi,
    }


def C(name, base, help, params=None):
    return {"name": name, "base": base, "help": help, "params": params or []}


_CHAN = P("Channel", "-c", "int", placeholder="1-14", help="Lock to this channel.")
_AUTH = "  Authorized testing only — targets you own or have written permission to test."


CATALOG = [
    # =====================================================================
    ("WiFi", [
        ("Recon & Scan", [
            C("Recon WiFi", "recon wifi",
              "Starts WiFi reconnaissance — discovers APs and stations and fills "
              "the target lists. View them under 'Lists & Targets'. Stop with "
              "'Recon Stop' or Stop Scan.", []),
            C("Recon Status", "recon status",
              "Prints the current recon state.", []),
            C("Scan All", "scanall",
              "Hops all channels logging every AP/station seen. Good for a full "
              "sweep before selecting targets.", []),
            C("Packet Count", "packetcount",
              "Live packets-per-second meter on the current channel.", []),
            C("MAC Track", "mactrack",
              "Tracks selected MAC(s) by presence and signal strength over time.", []),
            C("Wardrive", "wardrive",
              "Logs APs with GPS coordinates to the SD card (Wigle-compatible). "
              "Requires a GPS fix.", []),
            C("Wardrive POI", "wardrivepoi",
              "Tags a GPS point-of-interest during a wardrive.",
              [P("Label", None, "text", placeholder="optional label")]),
        ]),
        ("Sniffers", [
            C("Beacon Sniff", "sniffbeacon",
              "Captures 802.11 beacon frames from nearby APs.", []),
            C("Probe Sniff", "sniffprobe",
              "Captures probe-request frames — the networks nearby devices seek.", []),
            C("Deauth Sniff", "sniffdeauth",
              "Listens for deauth/disassoc frames in the air (detect attacks).", []),
            C("PMKID / EAPOL Sniff", "sniffpmkid",
              "Captures WPA PMKID / EAPOL handshake material to the SD card for "
              "offline analysis. Optionally force with deauth or loop channels.",
              [dict(_CHAN),
               P("Force (deauth)", "-d", "bool", help="Deauth clients to force a handshake."),
               P("Loop", "-l", "bool", help="Continuous / channel-looping capture.")]),
            C("SAE Sniff", "sniffsae",
              "Captures WPA3 SAE commit frames.", []),
            C("Pwnagotchi Sniff", "sniffpwn",
              "Detects nearby Pwnagotchi devices by their beacon signature.", []),
            C("Pineapple Sniff", "sniffpinescan",
              "Detects WiFi Pineapple rogue-AP devices nearby.", []),
            C("Multi-SSID Sniff", "sniffmultissid",
              "Detects APs broadcasting many SSIDs (Karma / MultiSSID behaviour).", []),
            C("Raw Sniff", "sniffraw",
              "Dumps raw 802.11 frames. High volume.", []),
        ]),
        ("Attacks", [
            C("Beacon Spam — List", "attack -t beacon -l",
              "Broadcasts beacons for every SSID in your SSID list." + _AUTH, []),
            C("Beacon Spam — Random", "attack -t beacon -r",
              "Broadcasts beacons with random SSIDs." + _AUTH, []),
            C("Beacon Spam — AP clones", "attack -t beacon -a",
              "Broadcasts beacons cloning your scanned AP list." + _AUTH, []),
            C("Rick Roll Beacon", "attack -t rickroll",
              "Broadcasts a set of joke SSIDs. Harmless demo.", []),
            C("Probe Flood", "attack -t probe",
              "Floods probe requests for SSIDs in your list." + _AUTH, []),
            C("Deauth", "attack -t deauth",
              "Sends deauth frames to selected AP(s)/station(s). Select targets "
              "first. Disrupts connectivity." + _AUTH,
              [dict(_CHAN),
               P("Source MAC", "-s", "text", placeholder="aa:bb:cc:dd:ee:ff"),
               P("Dest MAC", "-d", "text", placeholder="aa:bb:cc:dd:ee:ff")]),
            C("Bad Msg", "attack -t badmsg",
              "Sends malformed management frames to selected target(s)." + _AUTH,
              [dict(_CHAN)]),
            C("SAE Flood", "attack -t sae",
              "Floods WPA3 SAE commit frames at selected target(s)." + _AUTH, []),
            C("CSA (Channel Switch)", "attack -t csa",
              "Channel Switch Announcement attack against selected AP(s)." + _AUTH, []),
            C("Quiet", "attack -t quiet",
              "Sends 802.11 Quiet elements to selected target(s)." + _AUTH, []),
            C("Sleep", "attack -t sleep",
              "Sends power-save/sleep frames to selected target(s)." + _AUTH,
              [dict(_CHAN)]),
            C("Evil Portal — Start", "evilportal -c start",
              "Starts a captive-portal AP serving an HTML page (credential "
              "harvesting demo). Strictly authorized testing / labs only." + _AUTH,
              [P("HTML file", "-w", "text", placeholder="portal.html",
                 help="HTML page on the SD card to serve.")]),
            C("Evil Portal — Set HTML", "evilportal -c sethtml",
              "Selects the HTML page the Evil Portal serves." + _AUTH,
              [P("HTML file", None, "text", placeholder="portal.html")]),
            C("Karma", "karma -p",
              "Responds to probe requests to lure clients (Karma). Pick the probe "
              "index from 'List'." + _AUTH,
              [P("Probe index", None, "int", placeholder="e.g. 0")]),
        ]),
        ("IP / Network", [
            C("Join AP", "join",
              "Joins a scanned AP so the IP-layer tools below can run.",
              [P("AP index", "-a", "int", placeholder="e.g. 0", source="ap"),
               P("Password", "-p", "text", placeholder="network password")]),
            C("Join Status", "join -s",
              "Shows current WiFi-join / IP status.", []),
            C("Ping Scan", "pingscan",
              "Pings the local subnet to find live hosts (after Join).", []),
            C("ARP Scan", "arpscan",
              "ARP-sweeps the local subnet for hosts (after Join).",
              [P("Full", "-f", "bool", help="Full/aggressive sweep.")]),
            C("Port Scan — host", "portscan -a -t",
              "Scans common ports on a host from the ARP/host list.",
              [P("Host index", None, "int", placeholder="e.g. 2")]),
            C("Port Scan — service", "portscan -s",
              "Scans the subnet for a specific service.",
              [P("Service", None, "choice",
                 ["ssh", "telnet", "dns", "http", "smtp", "https", "rdp"])]),
            C("Protocol Info", "protocolinfo",
              "Prints protocol/traffic info seen on the network.", []),
        ]),
        ("Lists & Targets", [
            C("List APs", "list -a", "Prints scanned access points with indices.", []),
            C("List Stations", "list -s", "Prints scanned stations with indices.", []),
            C("List SSIDs", "list -c", "Prints your custom SSID list.", []),
            C("List (advanced)", "list",
              "Prints another internal list. Flags from firmware: -t -i -p -b -f "
              "-x -m (type/identify/portal/BLE/findmy/etc. — see 'help').",
              [P("Flag", None, "choice",
                 ["-a", "-s", "-c", "-t", "-i", "-p", "-b", "-f", "-x", "-m"],
                 default="-a")]),
            C("Info", "info",
              "Prints detailed info for an AP index (or current target).",
              [P("AP index", "-a", "int", placeholder="e.g. 0", source="ap")]),
            C("Select", "select",
              "Selects targets by index from a list. Pick the list, then "
              "double-click rows below to add them (or type indices).",
              [P("List", None, "choice", ["-a", "-s", "-c"], default="-a",
                 help="-a APs, -s stations, -c SSIDs."),
               P("Index(es)", None, "text", placeholder="e.g. 0,2,5",
                 source="auto", multi=True)]),
            C("Add SSID", "ssid -a",
              "Adds an SSID to your custom list (name, or N random).",
              [P("Name", "-n", "text", placeholder="MyTestSSID"),
               P("Random count", "-g", "int", placeholder="e.g. 5")]),
            C("Remove SSID", "ssid -r",
              "Removes an SSID from your list by index.",
              [P("Index", None, "int", placeholder="e.g. 0", source="ssid")]),
            C("Add AP (manual)", "add -a -b",
              "Manually adds an AP to the list by MAC.",
              [P("MAC", None, "text", placeholder="aa:bb:cc:dd:ee:ff"),
               P("Channel", "-ch", "int", placeholder="1-14"),
               P("SSID", "-e", "text", placeholder="optional name")]),
            C("Add Station (manual)", "add -c -b",
              "Manually adds a station by MAC, tied to an AP index.",
              [P("MAC", None, "text", placeholder="aa:bb:cc:dd:ee:ff"),
               P("AP index", "-ap", "int", placeholder="e.g. 0", source="ap")]),
            C("Clear list", "clearlist",
              "Empties a list.",
              [P("Which", None, "choice", ["-a", "-s", "-c"], default="-a",
                 help="-a APs, -s stations, -c SSIDs.")]),
            C("Save list", "save",
              "Saves a list to SD / flash.",
              [P("Which", None, "choice", ["-a", "-s"], default="-a")]),
            C("Load list", "load",
              "Loads a saved list.",
              [P("Which", None, "choice", ["-a", "-s"], default="-a")]),
            C("Upload (wardrive)", "upload",
              "Uploads logged wardrive data.",
              [P("Destination", "-d", "choice", ["wdg", "wigle", "both"], default="wigle")]),
        ]),
        ("MAC Tools", [
            C("Random AP MAC", "randapmac", "Randomizes the AP (soft-AP) MAC.", []),
            C("Random Station MAC", "randstamac", "Randomizes the station MAC.", []),
            C("Clone AP MAC", "cloneapmac -a",
              "Sets the AP MAC to match a scanned AP's.",
              [P("AP index", None, "int", placeholder="e.g. 0", source="ap")]),
            C("Clone Station MAC", "clonestamac -s",
              "Sets the station MAC to match a scanned station's.",
              [P("Station index", None, "int", placeholder="e.g. 0", source="sta")]),
        ]),
        ("Channel", [
            C("Get Channel", "channel", "Prints the current 802.11 channel.", []),
            C("Set Channel", "channel -s",
              "Sets the active 802.11 channel.",
              [P("Channel", None, "int", placeholder="1-14")]),
        ]),
    ]),
    # =====================================================================
    ("Bluetooth", [
        ("Recon & Sniff", [
            C("Recon BLE", "recon ble",
              "Starts BLE reconnaissance — discovers nearby Bluetooth devices.", []),
            C("Bluetooth Sniff", "sniffbt",
              "Sniffs BLE advertising traffic. Optionally filter to a device type.",
              [P("Type", "-t", "choice", ["airtag", "flipper", "flock", "meta"],
                 help="Filter the sniff to a device class.")]),
            C("AirTag Sniff", "sniffbt -t airtag",
              "Scans specifically for Apple AirTag / Find My beacons.", []),
            C("Flipper Sniff", "sniffbt -t flipper",
              "Scans specifically for Flipper Zero BLE advertisements.", []),
            C("Card Skimmer Detect", "sniffskim",
              "Scans for BLE signatures of known card-skimmer modules (defensive).", []),
        ]),
        ("Attacks", [
            C("Sour Apple", "blespam -t sourapple",
              "Spams Apple proximity-pairing adverts (crash/popup flood)." + _AUTH, []),
            C("Apple Juice", "blespam -t applejuice",
              "Apple BLE advert spam variant." + _AUTH, []),
            C("Google Spam", "blespam -t google",
              "Spams Google Fast Pair adverts." + _AUTH, []),
            C("Samsung Spam", "blespam -t samsung",
              "Spams Samsung pairing adverts." + _AUTH, []),
            C("Windows Swift Pair", "blespam -t windows",
              "Spams Microsoft Swift Pair adverts." + _AUTH, []),
            C("Flipper Spam", "blespam -t flipper",
              "Spams Flipper-style BLE adverts." + _AUTH, []),
            C("BLE Spam — All", "blespam -t all",
              "Cycles all of the above advert types." + _AUTH, []),
            C("Find My Spoof", "findmy -t",
              "Spoofs a Find My / AirTag advert from a scanned index." + _AUTH,
              [P("Index", None, "int", placeholder="e.g. 0")]),
            C("Spoof AirTag", "spoofat -t",
              "Spoofs a specific AirTag from a scanned index." + _AUTH,
              [P("Index", None, "int", placeholder="e.g. 0")]),
        ]),
    ]),
    # =====================================================================
    ("Device", [
        ("System", [
            C("Firmware Help", "help",
              "Prints the firmware's full command list — ground truth for syntax.", []),
            C("Show Settings", "settings",
              "Prints current settings (if the build supports a bare 'settings').", []),
            C("Change Setting", "settings -s",
              "Enables or disables a named setting (see Show Settings for names).",
              [P("Setting", None, "text", placeholder="e.g. ForcePMKID"),
               P("State", None, "choice", ["enable", "disable"], default="enable")]),
            C("Reset Settings", "settings -r", "Resets settings to defaults.", []),
            C("Reboot", "reboot", "Reboots the Marauder.", []),
            C("Update — SD", "update -s", "Flashes firmware from the SD card.", []),
            C("Update — Web", "update -w", "Starts a WiFi/OTA firmware update.", []),
        ]),
        ("Storage (SD)", [
            C("List Directory", "ls",
              "Lists a directory on the SD card.",
              [P("Path", None, "text", placeholder="/", default="/")]),
            C("Backup SPIFFS", "backupspiffs", "Copies internal SPIFFS to /spiffs on SD.", []),
            C("Backup Status", "backupstatus", "Inspects the /spiffs backup on SD.", []),
            C("Restore SPIFFS", "restorespiffs", "Restores SPIFFS from /spiffs on SD.", []),
        ]),
        ("LEDs & Display", [
            C("LED Color", "led -s",
              "Sets the LED to a hex color.",
              [P("Hex color", None, "text", placeholder="e.g. 00FF88")]),
            C("LED Rainbow", "led -p rainbow", "Runs the rainbow LED effect.", []),
            C("Brightness", "brightness -s",
              "Sets display brightness (0-9).",
              [P("Level", None, "choice", [str(i) for i in range(10)], default="5")]),
            C("Brightness Cycle", "brightness -c cycle",
              "Cycles through brightness levels.", []),
        ]),
        ("GPS", [
            C("GPS Data", "gpsdata", "Prints the current GPS data block.", []),
            C("GPS Query", "gps",
              "Queries a specific GPS field.",
              [P("Field", None, "choice",
                 ["fix", "sat", "lon", "lat", "alt", "date", "accuracy", "text", "nmea"]),
               P("Text form", "-t", "bool", help="Human-readable output."),
               P("Group", "-g", "bool", help="Grouped output.")]),
            C("NMEA Stream", "nmea", "Streams raw NMEA sentences from the GPS.", []),
            C("GPS POI", "gpspoi",
              "Start / mark / end a GPS point-of-interest capture.",
              [P("Action", None, "choice", ["-s", "-m", "-e"], default="-m",
                 help="-s start, -m mark, -e end.")]),
            C("GPS Tracker", "gpstracker -c",
              "Starts or stops GPS track logging.",
              [P("Action", None, "choice", ["start", "stop"], default="start")]),
        ]),
        ("Hunt", [
            C("Fox Hunt", "foxhunt",
              "Signal-strength 'hot/cold' hunt toward a target. Pick a mode and "
              "give the index/args: -w <ap>, -s <ap> <station>, -b <ble>, "
              "-t <findmy>, -f <flipper>, -p <pineapple>, -m <multissid>.",
              [P("Mode", None, "choice",
                 ["-w", "-s", "-b", "-t", "-f", "-p", "-m"], default="-w"),
               P("Index / args", None, "text", placeholder="e.g. 0")]),
        ]),
    ]),
]
