#!/bin/sh
# Build Galet and publish it to the signed Flatpak repository served by GitHub Pages
# (docs/repo → https://floderail.github.io/galet/repo/). Then commit and push docs/.
#
#   tools/publish-flatpak.sh                 # build the version pinned in flatpak/flathub/*.yml
#   tools/publish-flatpak.sh path/to/manifest.yml
#
# The signing key lives in ~/.local/share/galet-signing/gnupg (override with GALET_GPG_HOME).
set -e
APP_ID="io.github.FloDerail.Galet"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GPG_HOME="${GALET_GPG_HOME:-$HOME/.local/share/galet-signing/gnupg}"
KEY="${GALET_GPG_KEY:-FB3C833A7E51613E}"
MANIFEST="${1:-$ROOT/flatpak/flathub/$APP_ID.yml}"
SITE="https://floderail.github.io/galet"
cd "$ROOT"

echo "→ Building $APP_ID (branch stable)…"
flatpak run org.flatpak.Builder --user --force-clean --disable-rofiles-fuse \
    --default-branch=stable --repo=repo build-dir "$MANIFEST"

echo "→ Signing and exporting to docs/repo…"
[ -d docs/repo/objects ] || ostree init --mode=archive-z2 --repo=docs/repo
flatpak build-commit-from --src-repo=repo --gpg-sign="$KEY" --gpg-homedir="$GPG_HOME" \
    docs/repo "app/$APP_ID/x86_64/stable"
flatpak build-update-repo --gpg-sign="$KEY" --gpg-homedir="$GPG_HOME" \
    --title="Galet" --default-branch=stable --generate-static-deltas --prune --prune-depth=3 docs/repo

echo "→ Writing install files…"
GPGKEY="$(gpg --homedir "$GPG_HOME" --export "$KEY" | base64 -w 0)"
cat > docs/galet.flatpakrepo <<REPO
[Flatpak Repo]
Title=Galet
Url=$SITE/repo/
Homepage=$SITE/
Comment=Galet, the Finder-inspired file manager by Florian Dérail
Description=Official Flatpak repository of Galet
Icon=$SITE/assets/logo-128.png
GPGKey=$GPGKEY
REPO
cat > docs/galet.flatpakref <<REF
[Flatpak Ref]
Name=$APP_ID
Branch=stable
Title=Galet
Url=$SITE/repo/
SuggestRemoteName=galet
RuntimeRepo=https://dl.flathub.org/repo/flathub.flatpakrepo
IsRuntime=false
Homepage=$SITE/
Comment=Finder-inspired file manager with colour tags
Icon=$SITE/assets/logo-128.png
GPGKey=$GPGKEY
REF

echo "✓ Done. Publish with:  git add docs && git commit -m 'Publish Flatpak' && git push"
