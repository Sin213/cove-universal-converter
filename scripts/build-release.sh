#!/usr/bin/env bash
# Build .AppImage and .deb for Cove Universal Converter.
#
# Requires:
#   - python3 (with pip)
#   - ar, tar, xz, curl
# Downloads static ffmpeg + pandoc binaries automatically.
#
# Output lands in release/.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

APP_NAME="cove-universal-converter"
DISPLAY_NAME="Cove Universal Converter"
# Single source of truth: pyproject.toml. Override with VERSION=… if needed.
PYPROJECT_VERSION="$(grep -E '^version *= *' "$ROOT/pyproject.toml" | head -1 | sed -E 's/^version *= *"([^"]+)".*/\1/')"
VERSION="${VERSION:-${PYPROJECT_VERSION:-1.0.0}}"
ARCH="x86_64"
DEB_ARCH="amd64"
RELEASE_DIR="$ROOT/release"
DIST_DIR="$ROOT/dist"
APPDIR="$ROOT/build/AppDir"
DEB_BUILD="$ROOT/build/deb"
BUILD_ENV="$ROOT/.buildenv"
ICON_SRC="$ROOT/cove_icon.png"

LOCAL_BIN="${HOME}/.local/bin"
APPIMAGETOOL="${LOCAL_BIN}/appimagetool"

# Pandoc release version to bundle.
PANDOC_VERSION="3.1.13"

# FFmpeg static-build asset to bundle. johnvansickle.com only publishes a
# single rolling release URL:
#   https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz
# That URL is mutable — every time upstream cuts a new build, the bytes
# behind it change. There is no per-version path. To stay fail-closed we
# pin FFMPEG_SHA256 against the exact bytes we expect; a mismatch aborts
# the build before anything is extracted into the AppImage / .deb.
#
# MAINTAINER NOTE: when CI starts failing the SHA-256 check, upstream has
# rotated the release. Download the new tarball, run ``sha256sum`` on it,
# verify it against johnvansickle.com's published hash, then bump
# FFMPEG_VERSION (informational only) and FFMPEG_SHA256 here in the same
# commit. Do NOT remove the verification step.
FFMPEG_VERSION="${FFMPEG_VERSION:-7.0.2}"
FFMPEG_URL="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"

# Pinned SHA-256 digests for the upstream archives we bundle. A mismatch
# here aborts the build before any downloaded bytes are extracted into the
# AppImage / .deb. Regenerate with `sha256sum <file>` after upstream
# rotates the asset, verify against the upstream signature/hash, and
# commit the new digest alongside the version bump.
FFMPEG_SHA256="${FFMPEG_SHA256:-abda8d77ce8309141f83ab8edf0596834087c52467f6badf376a6a2a4c87cf67}"
PANDOC_SHA256="db556c98cf207d2fddc088d12d2e2f367d9401784d4a3e914b068fa895dcf3f0"

if [ -z "$FFMPEG_SHA256" ]; then
    cat >&2 <<'EOF'
ERROR: Linux release builds require a pinned FFmpeg SHA-256.

       Set FFMPEG_SHA256 (either at the top of scripts/build-release.sh
       or as an environment variable) to the digest of the current
       johnvansickle.com release asset:

           ffmpeg-release-amd64-static.tar.xz

       That URL is mutable — upstream rotates it on every new build — so
       the digest must be refreshed in lockstep. Fail closed rather than
       silently bundle a different ffmpeg than the one that was reviewed.
EOF
    exit 1
fi

mkdir -p "$RELEASE_DIR" "$LOCAL_BIN"
rm -rf "$DIST_DIR" "$ROOT/build"
mkdir -p "$ROOT/build"

# ----------------------------------------------------------------------
# 0. Build venv
# ----------------------------------------------------------------------
echo "==> Creating build venv"
rm -rf "$BUILD_ENV"
python3 -m venv "$BUILD_ENV"
"$BUILD_ENV/bin/pip" install --quiet --upgrade pip
"$BUILD_ENV/bin/pip" install --quiet -r requirements.txt pyinstaller

# ----------------------------------------------------------------------
# 1. Download ffmpeg + pandoc static builds
# ----------------------------------------------------------------------
echo "==> Fetching ffmpeg static build (expecting $FFMPEG_VERSION)"
FF_TMP="$ROOT/build/ff"
mkdir -p "$FF_TMP"
curl -fL --retry 3 --silent --show-error \
    -o "$FF_TMP/ffmpeg.tar.xz" \
    "$FFMPEG_URL"
echo "==> Verifying ffmpeg archive against pinned SHA-256"
echo "$FFMPEG_SHA256  $FF_TMP/ffmpeg.tar.xz" | sha256sum -c -
(cd "$FF_TMP" && tar -xf ffmpeg.tar.xz)
FFMPEG_BIN="$(find "$FF_TMP" -type f -name ffmpeg | head -1)"
[ -n "$FFMPEG_BIN" ] || { echo "ffmpeg not found after extract"; exit 1; }

echo "==> Fetching pandoc $PANDOC_VERSION"
PD_TMP="$ROOT/build/pd"
mkdir -p "$PD_TMP"
curl -fL --retry 3 --silent --show-error \
    -o "$PD_TMP/pandoc.tar.gz" \
    "https://github.com/jgm/pandoc/releases/download/${PANDOC_VERSION}/pandoc-${PANDOC_VERSION}-linux-amd64.tar.gz"
echo "==> Verifying pandoc archive against pinned SHA-256"
echo "$PANDOC_SHA256  $PD_TMP/pandoc.tar.gz" | sha256sum -c -
(cd "$PD_TMP" && tar -xf pandoc.tar.gz)
PANDOC_BIN="$(find "$PD_TMP" -type f -name pandoc | head -1)"
[ -n "$PANDOC_BIN" ] || { echo "pandoc not found after extract"; exit 1; }

# ----------------------------------------------------------------------
# 2. PyInstaller
# ----------------------------------------------------------------------
echo "==> Running PyInstaller"
"$BUILD_ENV/bin/pyinstaller" \
    --noconfirm --clean --log-level WARN \
    --windowed \
    --name "$APP_NAME" \
    --paths . \
    --add-data "cove_icon.png:." \
    --add-binary "${FFMPEG_BIN}:." \
    --add-binary "${PANDOC_BIN}:." \
    --hidden-import pypdf \
    --hidden-import pillow_heif \
    --collect-all reportlab \
    --collect-all xhtml2pdf \
    --collect-all html5lib \
    --collect-all svglib \
    --exclude-module PySide6.QtWebEngineCore \
    --exclude-module PySide6.QtWebEngineWidgets \
    --exclude-module PySide6.QtQml \
    --exclude-module PySide6.QtQuick \
    --exclude-module PySide6.QtPdf \
    --exclude-module PySide6.Qt3DCore \
    --exclude-module PySide6.QtCharts \
    --exclude-module PySide6.QtDataVisualization \
    --exclude-module tkinter \
    packaging/launcher.py

BUNDLE="$DIST_DIR/$APP_NAME"
[ -d "$BUNDLE" ] || { echo "PyInstaller bundle not found at $BUNDLE"; exit 1; }

# ----------------------------------------------------------------------
# 3. AppImage
# ----------------------------------------------------------------------
echo "==> Assembling AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/lib/$APP_NAME" \
         "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/256x256/apps"

cp -r "$BUNDLE"/. "$APPDIR/usr/lib/$APP_NAME/"
cp "$ICON_SRC" "$APPDIR/usr/share/icons/hicolor/256x256/apps/$APP_NAME.png"
cp "$ICON_SRC" "$APPDIR/$APP_NAME.png"
cp "$ICON_SRC" "$APPDIR/.DirIcon" 2>/dev/null || true

cat > "$APPDIR/$APP_NAME.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=$DISPLAY_NAME
GenericName=File Format Converter
Comment=Batch-convert video, audio, images, and documents offline
Exec=$APP_NAME
Icon=$APP_NAME
Terminal=false
Categories=AudioVideo;Video;Audio;Graphics;Office;Utility;
Keywords=convert;video;audio;image;document;pdf;ffmpeg;pandoc;
StartupNotify=true
EOF
cp "$APPDIR/$APP_NAME.desktop" "$APPDIR/usr/share/applications/$APP_NAME.desktop"

cat > "$APPDIR/AppRun" <<EOF
#!/usr/bin/env bash
HERE="\$(dirname "\$(readlink -f "\${0}")")"
export PATH="\$HERE/usr/bin:\$PATH"
export LD_LIBRARY_PATH="\$HERE/usr/lib/$APP_NAME:\${LD_LIBRARY_PATH:-}"
exec "\$HERE/usr/lib/$APP_NAME/$APP_NAME" "\$@"
EOF
chmod +x "$APPDIR/AppRun"

cat > "$APPDIR/usr/bin/$APP_NAME" <<EOF
#!/usr/bin/env bash
HERE="\$(dirname "\$(readlink -f "\${0}")")/../lib/$APP_NAME"
exec "\$HERE/$APP_NAME" "\$@"
EOF
chmod +x "$APPDIR/usr/bin/$APP_NAME"

if [ ! -x "$APPIMAGETOOL" ]; then
    if command -v appimagetool >/dev/null 2>&1; then
        APPIMAGETOOL="$(command -v appimagetool)"
    else
        echo "==> Downloading appimagetool to $APPIMAGETOOL"
        curl -fL --retry 3 --silent --show-error -o "$APPIMAGETOOL" \
            "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
        chmod +x "$APPIMAGETOOL"
    fi
fi

echo "==> Building AppImage"
APPIMAGE_OUT="$RELEASE_DIR/${DISPLAY_NAME// /-}-${VERSION}-${ARCH}.AppImage"
ARCH=$ARCH "$APPIMAGETOOL" --no-appstream "$APPDIR" "$APPIMAGE_OUT"
chmod +x "$APPIMAGE_OUT"
echo "    -> $APPIMAGE_OUT"

# ----------------------------------------------------------------------
# 4. .deb (manual: ar + tar.xz, no dpkg-deb dependency)
# ----------------------------------------------------------------------
echo "==> Assembling .deb tree"
PKG_ROOT="$DEB_BUILD/${APP_NAME}_${VERSION}_${DEB_ARCH}"
rm -rf "$DEB_BUILD"
mkdir -p "$PKG_ROOT/DEBIAN" \
         "$PKG_ROOT/usr/bin" \
         "$PKG_ROOT/usr/lib/$APP_NAME" \
         "$PKG_ROOT/usr/share/applications" \
         "$PKG_ROOT/usr/share/icons/hicolor/256x256/apps" \
         "$PKG_ROOT/usr/share/doc/$APP_NAME"

cp -r "$BUNDLE"/. "$PKG_ROOT/usr/lib/$APP_NAME/"
cp "$ICON_SRC" "$PKG_ROOT/usr/share/icons/hicolor/256x256/apps/$APP_NAME.png"

cat > "$PKG_ROOT/usr/bin/$APP_NAME" <<EOF
#!/usr/bin/env bash
exec /usr/lib/$APP_NAME/$APP_NAME "\$@"
EOF
chmod +x "$PKG_ROOT/usr/bin/$APP_NAME"

cat > "$PKG_ROOT/usr/share/applications/$APP_NAME.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=$DISPLAY_NAME
GenericName=File Format Converter
Comment=Batch-convert video, audio, images, and documents offline
Exec=$APP_NAME
Icon=$APP_NAME
Terminal=false
Categories=AudioVideo;Video;Audio;Graphics;Office;Utility;
Keywords=convert;video;audio;image;document;pdf;ffmpeg;pandoc;
StartupNotify=true
EOF

cp "$ROOT/LICENSE" "$PKG_ROOT/usr/share/doc/$APP_NAME/copyright"

INSTALLED_SIZE=$(du -sk "$PKG_ROOT/usr" | awk '{print $1}')

cat > "$PKG_ROOT/DEBIAN/control" <<EOF
Package: $APP_NAME
Version: $VERSION
Architecture: $DEB_ARCH
Maintainer: Cove <noreply@cove.local>
Installed-Size: $INSTALLED_SIZE
Section: utils
Priority: optional
Homepage: https://github.com/Sin213/cove-universal-converter
Description: Offline batch converter for video, audio, images, and documents
 Cove Universal Converter is a privacy-first desktop tool that batch-converts
 files between 40+ formats. Video and audio via ffmpeg, images via Pillow,
 documents via pandoc, PDFs via pypdf + xhtml2pdf. Drag and drop, queue-based,
 fully offline.
EOF

echo "==> Building .deb archive"
DEB_OUT="$RELEASE_DIR/${APP_NAME}_${VERSION}_${DEB_ARCH}.deb"
WORK="$DEB_BUILD/work"
rm -rf "$WORK"
mkdir -p "$WORK"

(cd "$PKG_ROOT" && tar --xz --owner=0 --group=0 -cf "$WORK/control.tar.xz" -C DEBIAN .)
(cd "$PKG_ROOT" && tar --xz --owner=0 --group=0 -cf "$WORK/data.tar.xz" \
    --transform 's,^\./,,' \
    --exclude=./DEBIAN \
    .)
echo -n "2.0" > "$WORK/debian-binary"
echo "" >> "$WORK/debian-binary"

(cd "$WORK" && ar -rc "$DEB_OUT" debian-binary control.tar.xz data.tar.xz)

echo "    -> $DEB_OUT"

# ----------------------------------------------------------------------
# 5. SHA-256 sidecars
# ----------------------------------------------------------------------
# Cove Nexus is moving toward mandatory checksum verification — every
# shipped binary must have a matching `<asset>.sha256` published in the
# same release. Sidecars use the relative-name form so `sha256sum -c` works
# against the local file regardless of where the user dropped the pair.
echo "==> Writing SHA-256 sidecars"
(cd "$RELEASE_DIR" && sha256sum "$(basename "$APPIMAGE_OUT")" > "$(basename "$APPIMAGE_OUT").sha256")
(cd "$RELEASE_DIR" && sha256sum "$(basename "$DEB_OUT")"      > "$(basename "$DEB_OUT").sha256")
echo "    -> $APPIMAGE_OUT.sha256"
echo "    -> $DEB_OUT.sha256"

# ----------------------------------------------------------------------
# Done
# ----------------------------------------------------------------------
echo ""
echo "Release artifacts in $RELEASE_DIR:"
ls -lh "$RELEASE_DIR"
