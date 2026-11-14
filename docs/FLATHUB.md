# Publier Galet sur Flathub — guide pour Florian

Flathub est la vitrine principale des Logithèques Linux. Ses règles (2026) demandent que **la
demande soit faite par un humain, sans outil d'IA** (ni pour rédiger la demande, ni pour répondre
aux relecteurs), et que l'application ait **un vrai historique**. Ce guide t'aide à préparer le
terrain ; la demande elle-même, c'est toi qui l'écris.

## 1. Avant de déposer (quelques mois)
- Utiliser Galet au quotidien, corriger les bugs, publier des versions régulières
  (`tools/publish-flatpak.sh` met à jour le dépôt Flatpak du site).
- Recueillir des retours : issues GitHub, étoiles, utilisateurs du dépôt Flatpak.

## 2. Préparer la demande
- Relire les règles : https://docs.flathub.org/docs/for-app-authors/requirements
  et le guide : https://docs.flathub.org/docs/for-app-authors/submission
- Mettre à jour `flatpak/flathub/io.github.FloDerail.Galet.yml` sur le dernier tag
  (`tag:` et `commit:`), puis vérifier :
  ```sh
  flatpak run org.flatpak.Builder --user --force-clean build-dir flatpak/flathub/io.github.FloDerail.Galet.yml
  flatpak run --command=flatpak-builder-lint org.flatpak.Builder manifest flatpak/flathub/io.github.FloDerail.Galet.yml
  ```
- Enregistrer une **vidéo** de Galet en Flatpak : `Ctrl+Alt+Maj+R` (enregistreur d'écran de Zorin),
  puis `flatpak run io.github.FloDerail.Galet`. Montrer tags, colonnes, recherche, thèmes.

## 3. Déposer (toi-même, à la main)
1. Sur GitHub, dans ton fork `FloDerail/flathub`, partir de la branche `new-pr`.
2. Ajouter le fichier `io.github.FloDerail.Galet.yml`.
3. Ouvrir une Pull Request vers `flathub/flathub`, branche **`new-pr`**.
4. Remplir **toi-même** le modèle de la PR et cocher honnêtement chaque case, y compris la
   déclaration du contenu généré par IA dans l'application.
5. Joindre la vidéo, répondre aux relecteurs toi-même.

La permission `--talk-name=org.freedesktop.Flatpak` (lancer des programmes du système : miniatures,
terminal, pdftotext, 7z) sera sûrement discutée : elle est utilisée dans `galet/sandbox.py`.
