#!/bin/sh
# Install Galet for the current user (no root needed).
#   ./install.sh            install
#   ./install.sh --default  install and make Galet the default file manager
#   ./install.sh --remove   uninstall
set -e
APP_ID="io.github.FloDerail.Galet"
SRC="$(cd "$(dirname "$0")" && pwd)"
PREFIX="${XDG_DATA_HOME:-$HOME/.local/share}"
DEST="$PREFIX/galet"
BIN="$HOME/.local/bin/galet"
DESKTOP="$PREFIX/applications/$APP_ID.desktop"
ICONS="$PREFIX/icons/hicolor"
DBUS_SERVICE="$PREFIX/dbus-1/services/org.freedesktop.FileManager1.service"

if [ "$1" = "--remove" ]; then
    rm -f "$BIN" "$DESKTOP" "$PREFIX/applications/galet.desktop"
    rm -f "$ICONS/scalable/apps/$APP_ID.svg" "$ICONS/symbolic/apps/$APP_ID-symbolic.svg" "$DBUS_SERVICE"
    rm -rf "$DEST"
    echo "Galet removed (your tags and settings in ~/.config/galet are kept)."
    exit 0
fi

mkdir -p "$DEST" "$HOME/.local/bin" "$PREFIX/applications" "$ICONS/scalable/apps" "$ICONS/symbolic/apps"
cp -r "$SRC/galet" "$SRC/po" "$SRC/data" "$SRC/bin" "$DEST/"
ln -sf "$DEST/bin/galet" "$BIN"
sed "s|@BIN@|$BIN|" "$SRC/data/$APP_ID.desktop.in" > "$DESKTOP"
rm -f "$PREFIX/applications/galet.desktop"   # name used by version 0.1/0.2
cp "$SRC/data/icons/hicolor/scalable/apps/$APP_ID.svg" "$ICONS/scalable/apps/"
cp "$SRC/data/icons/hicolor/symbolic/apps/$APP_ID-symbolic.svg" "$ICONS/symbolic/apps/"
gtk-update-icon-cache -q -t -f "$ICONS" 2>/dev/null || true
update-desktop-database "$PREFIX/applications" 2>/dev/null || true

if [ "$1" = "--default" ]; then
    xdg-mime default "$APP_ID.desktop" inode/directory
    # Apps like VS Code or web browsers ("Show in folder") use the FileManager1 D-Bus
    # service instead of the default application: let Galet answer it too.
    mkdir -p "$(dirname "$DBUS_SERVICE")"
    printf '[D-BUS Service]\nName=org.freedesktop.FileManager1\nExec=%s --gapplication-service\n' "$BIN" > "$DBUS_SERVICE"
    # GNOME Files may be running in the background and still own the service.
    if command -v nautilus >/dev/null 2>&1; then nautilus -q 2>/dev/null || true; fi
    echo "Galet is now the default file manager (also for “Show in folder” in other apps)."
fi
echo "Galet installed. Launch it from the applications menu or run: galet"
