#!/usr/bin/env bash
# build_deb.sh — package the PyInstaller onefile build as a self-contained .deb.
#
# The .deb bundles its own Python runtime (via PyInstaller), so the only hard
# dependency is a C library present on every Debian/Ubuntu/Kali system. Serial
# access still requires the invoking user to be in the "dialout" group; that is
# a per-user change an installer must not make silently, so it is documented in
# the package description and README instead of forced in a maintainer script.
#
# Usage:
#   tools/build_deb.sh                 # expects dist/MarauderV8-Control already built
#   BUILD=1 tools/build_deb.sh         # run PyInstaller first, then package
#
# Output: dist/specter-v8_<version>_<arch>.deb
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

PKG="specter-v8"
ARCH="$(dpkg --print-architecture)"
BIN_SRC="dist/MarauderV8-Control"
MAINTAINER="Anon0ne <anon0ne@users.noreply.github.com>"
HOMEPAGE="https://github.com/Anon0ne/marauder-v8-gui"

# Version: read __version__ and convert PEP 440 (0.4.4-beta.1) to a Debian
# upstream version (0.4.4~beta.1) so pre-releases sort before the final 0.4.4.
PYVER="$(python3 -c "import re,io; s=open('marauder_gui.py').read(); print(re.search(r'__version__\s*=\s*[\"\x27]([^\"\x27]+)',s).group(1))")"
DEBVER="${PYVER//-/\~}"

if [ "${BUILD:-0}" = "1" ] || [ ! -x "$BIN_SRC" ]; then
  echo ">> Building PyInstaller onefile…"
  python3 tools/collect_public_licenses.py 2>/dev/null || echo "   (license lock mismatch — bundling whatever notices are present)"
  pyinstaller --noconfirm --clean MarauderV8-Control.spec
fi
[ -x "$BIN_SRC" ] || { echo "ERROR: $BIN_SRC not found — build it first"; exit 1; }

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
echo ">> Staging into $STAGE"

install -D -m0755 "$BIN_SRC"                       "$STAGE/opt/${PKG}/MarauderV8-Control"
install -d                                          "$STAGE/usr/bin"
ln -s "/opt/${PKG}/MarauderV8-Control"             "$STAGE/usr/bin/${PKG}"
install -D -m0644 packaging/linux/${PKG}.desktop   "$STAGE/usr/share/applications/${PKG}.desktop"

# Icon: convert the bundled .ico to one 256x256 PNG for the hicolor theme.
# An .ico holds several frames; pick the largest, then fit it to 256x256 so
# the theme resolves exactly one file named "${PKG}.png" (Icon=${PKG}).
ICON_DIR="$STAGE/usr/share/icons/hicolor/256x256/apps"
install -d "$ICON_DIR"
if command -v convert >/dev/null 2>&1; then
  FRAME="$(identify -format '%p %w\n' "marauder.ico" 2>/dev/null | sort -k2 -n | tail -1 | cut -d' ' -f1)"
  FRAME="${FRAME:-0}"
  convert "marauder.ico[${FRAME}]" -background none -resize 256x256 \
          -gravity center -extent 256x256 "$ICON_DIR/${PKG}.png"
  chmod 0644 "$ICON_DIR/${PKG}.png"
else
  echo "   (ImageMagick absent — skipping icon; .desktop will fall back to a generic icon)"
fi

# Docs: copyright + a minimal Debian changelog.
DOC="$STAGE/usr/share/doc/${PKG}"
install -d "$DOC"
cat > "$DOC/copyright" <<EOF
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: Specter V8 Control
Source: ${HOMEPAGE}

Files: *
Copyright: Specter V8 / Marauder V8 project (Anon0ne)
License: MIT
 This desktop control application is released under the MIT License.
 It bundles third-party components (esptool, pyserial, the Python runtime
 and others) under their own licenses; see /opt/${PKG} and the bundled
 third_party_licenses directory for their notices.
EOF
{
  echo "${PKG} (${DEBVER}) unstable; urgency=low"
  echo
  echo "  * Public beta build ${PYVER}. Self-contained desktop control app for"
  echo "    Specter / Marauder V8 (ESP32-C5) WiFi & BLE firmware."
  echo
  echo " -- ${MAINTAINER}  $(date -R)"
} > "$DOC/changelog.Debian"
gzip -9n "$DOC/changelog.Debian"
chmod 0644 "$DOC/copyright" "$DOC/changelog.Debian.gz"

# Control + size.
INSTALLED_KB="$(du -ks "$STAGE" | cut -f1)"
install -d "$STAGE/DEBIAN"
cat > "$STAGE/DEBIAN/control" <<EOF
Package: ${PKG}
Version: ${DEBVER}
Architecture: ${ARCH}
Maintainer: ${MAINTAINER}
Installed-Size: ${INSTALLED_KB}
Depends: libc6
Section: utils
Priority: optional
Homepage: ${HOMEPAGE}
Description: Specter / Marauder V8 WiFi & BLE control (public beta)
 Desktop control application for the Specter / Marauder V8 (ESP32-C5) WiFi and
 BLE assessment firmware. Flash firmware, drive Evil Portal template exercises,
 run the Specter BLE / BT+ suite (including the BadBLE DuckyScript keyboard),
 browse the device SD card and manage capture sessions.
 .
 This build is self-contained: it bundles its own Python runtime and esptool,
 so no system Python is required. Serial access to the device needs the running
 user to be a member of the "dialout" group:
 .
   sudo usermod -aG dialout \$USER   # then log out and back in
 .
 Authorized testing only. Tested on Marauder V8 (ESP32-C5) so far.
EOF

OUT="dist/${PKG}_${DEBVER}_${ARCH}.deb"
echo ">> Building $OUT"
fakeroot dpkg-deb --build "$STAGE" "$OUT"
echo ">> Done:"
dpkg-deb -I "$OUT" | sed 's/^/   /'
ls -la "$OUT"
