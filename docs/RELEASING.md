# Publier une nouvelle version de Galet

1. Changer le numéro dans `galet/__init__.py` (`__version__`), ajouter la version en haut de
   `CHANGELOG.md` et une ligne `<release>` dans `data/io.github.FloDerail.Galet.metainfo.xml`.
2. Commiter, pousser, puis créer le tag :
   ```sh
   git commit -am "Galet X.Y.Z" && git push
   git tag -a vX.Y.Z -m "Galet X.Y.Z" && git push origin vX.Y.Z
   ```
3. Dans `flatpak/flathub/io.github.FloDerail.Galet.yml`, mettre `tag: vX.Y.Z` et
   `commit:` = résultat de `git rev-parse vX.Y.Z^{commit}`.
4. Publier dans le dépôt Flatpak (Logithèque) et pousser :
   ```sh
   tools/publish-flatpak.sh
   git add -A && git commit -m "Publish Galet X.Y.Z in the Flatpak repository" && git push
   ```
   Les utilisateurs reçoivent la mise à jour automatiquement (quelques minutes de cache GitHub Pages).
5. (Facultatif) Fichier `.flatpak` pour la page Releases :
   ```sh
   flatpak build-bundle --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo repo dist/galet.flatpak io.github.FloDerail.Galet stable
   gh release create vX.Y.Z dist/galet.flatpak --title "Galet X.Y.Z" --notes "…"
   ```

## La clé de signature
- Elle se trouve dans `~/.local/share/galet-signing/gnupg` (identifiant `FB3C833A7E51613E`).
- **Sauvegarde-la** (clé USB, coffre de mots de passe) :
  `tar czf galet-signing-key.tar.gz -C ~/.local/share galet-signing`
- Si elle est perdue, les utilisateurs ne pourront plus recevoir de mises à jour sans réinstaller.
  Si elle est volée, quelqu'un pourrait signer de fausses versions : ne la partage jamais.
