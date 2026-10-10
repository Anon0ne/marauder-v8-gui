# Firmware command comparison

Official firmware reference: d3ceb28afeda1196ca27c13adeaa69ada52383f3

96 catalog entries. Token presence does not establish full flag support or board capability. GPS queries use gps -g FIELD; gps -t is a separate mode-changing action.

| Command | Official token |
| --- | --- |
| `recon wifi` | Present |
| `recon status` | Present |
| `scanall` | Present |
| `packetcount` | Present |
| `mactrack` | Present |
| `sigmon` | Legacy/unverified |
| `wardrive` | Present |
| `wardrivepoi` | Present |
| `sniffbeacon` | Present |
| `sniffprobe` | Present |
| `sniffdeauth` | Present |
| `sniffpmkid` | Present |
| `sniffsae` | Present |
| `sniffesp` | Legacy/unverified |
| `sniffpwn` | Present |
| `sniffpinescan` | Present |
| `sniffmultissid` | Present |
| `sniffraw` | Present |
| `attack -t beacon -l` | Present |
| `attack -t beacon -r` | Present |
| `attack -t beacon -a` | Present |
| `attack -t rickroll` | Present |
| `attack -t probe` | Present |
| `attack -t deauth` | Present |
| `attack -t badmsg` | Present |
| `attack -t sae` | Present |
| `attack -t csa` | Present |
| `attack -t quiet` | Present |
| `attack -t sleep` | Present |
| `evilportal -c start` | Present |
| `evilportal -c sethtml` | Present |
| `karma -p` | Present |
| `join` | Present |
| `join -s` | Present |
| `pingscan` | Present |
| `arpscan` | Present |
| `portscan -a -t` | Present |
| `portscan -s` | Present |
| `protocolinfo` | Present |
| `list -a` | Present |
| `list -s` | Present |
| `list -c` | Present |
| `list` | Present |
| `info` | Present |
| `select` | Present |
| `ssid -a` | Present |
| `ssid -r` | Present |
| `add -a -b` | Present |
| `add -c -b` | Present |
| `clearlist` | Present |
| `save` | Present |
| `load` | Present |
| `upload` | Present |
| `randapmac` | Legacy/unverified |
| `randstamac` | Legacy/unverified |
| `cloneapmac -a` | Legacy/unverified |
| `clonestamac -s` | Legacy/unverified |
| `channel` | Present |
| `channel -s` | Present |
| `recon ble` | Present |
| `sniffbt` | Present |
| `sniffbt -t airtag` | Present |
| `sniffbt -t flipper` | Present |
| `sniffskim` | Present |
| `btwardrive` | Legacy/unverified |
| `blespam -t sourapple` | Present |
| `blespam -t applejuice` | Present |
| `blespam -t google` | Present |
| `blespam -t samsung` | Present |
| `blespam -t windows` | Present |
| `blespam -t flipper` | Present |
| `blespam -t all` | Present |
| `findmy -t` | Present |
| `spoofat -t` | Present |
| `help` | Present |
| `settings` | Present |
| `settings -s` | Present |
| `settings -r` | Present |
| `reboot` | Present |
| `update -s` | Present |
| `update -w` | Present |
| `ls` | Present |
| `backupspiffs` | Present |
| `backupstatus` | Present |
| `restorespiffs` | Present |
| `led -s` | Present |
| `led -p rainbow` | Present |
| `brightness -s` | Present |
| `brightness -c cycle` | Present |
| `gpsdata` | Present |
| `gps` | Present |
| `gps -t` | Present |
| `nmea` | Present |
| `gpspoi` | Present |
| `gpstracker -c` | Legacy/unverified |
| `foxhunt` | Present |
