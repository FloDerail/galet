#!/bin/sh
# Install Galet for the current user (no root needed).
#   ./install.sh            install
#   ./install.sh --default  install and make Galet the default file manager
#   ./install.sh --remove   uninstall
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"
PREFIX="${XDG_DATA_HOME:-$HOME/.local/share}"
DEST="$PREFIX/galet"
BIN="$HOME/.local/bin/galet"
DESKTOP="$PREFIX/applications/galet.desktop"

if [ "$1" = "--remove" ]; then
    rm -f "$BIN" "$DESKTOP"
    rm -rf "$DEST"
    echo "Galet removed (your tags and settings in ~/.config/galet are kept)."
    exit 0
fi

mkdir -p "$DEST" "$HOME/.local/bin" "$PREFIX/applications"
cp -r "$SRC/galet" "$SRC/po" "$SRC/data" "$SRC/bin" "$DEST/"
ln -sf "$DEST/bin/galet" "$BIN"
sed "s|@BIN@|$BIN|" "$SRC/data/galet.desktop.in" > "$DESKTOP"
update-desktop-database "$PREFIX/applications" 2>/dev/null || true

if [ "$1" = "--default" ]; then
    xdg-mime default galet.desktop inode/directory
    echo "Galet is now the default file manager."
fi
echo "Galet installed. Launch it from the applications menu or run: galet"
