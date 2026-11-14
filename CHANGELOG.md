# Nouveautés / Changelog

Galet — logiciel libre et open source de [Florian Dérail](https://florianderail.fr).

## 0.6.3 — Clic droit vraiment corrigé (version Flatpak)

- 🖱️ Le clic droit sur un fichier ou un dossier ouvre de nouveau le menu complet (couleur du
  dossier, tags, actions rapides…) dans la version Flatpak / Logithèque. Avec la version récente de
  Python qu'elle utilise, Galet perdait la trace de la ligne cliquée et croyait cliquer dans le vide.
- 🖐️ Même correction pour le glisser-déposer depuis la version Flatpak.
- 🇬🇧 Right-click and drag and drop fixed in the Flatpak build (newer PyGObject freed list item wrappers).

## 0.6.2 — Clic droit corrigé

- 🖱️ Le **clic droit** sur les fichiers et dossiers fonctionne à nouveau avec les versions récentes de
  GTK (version Flatpak / Logithèque) : couleur du dossier, tags, actions rapides…
- ⌨️ **Maj+F10** et la touche **Menu** ouvrent aussi le menu contextuel.
- 🇬🇧 Right-click menu fixed with recent GTK (Flatpak); Shift+F10 and the Menu key open it too.

## 0.6.1 — Galet s'ouvre aussi depuis VS Code et les navigateurs

- 📂 « Afficher dans le dossier » / « Reveal in File Explorer » (VS Code, navigateurs, gestionnaires de
  téléchargement…) ouvre maintenant **Galet** au lieu de l'ancien explorateur, avec le fichier
  sélectionné. Galet fournit le service système `org.freedesktop.FileManager1` (installé par
  `./install.sh --default`).
- 📄 `galet fichier.txt` ouvre le dossier et sélectionne le fichier.
- 🇬🇧 Galet now provides the org.freedesktop.FileManager1 D-Bus service, so "Show in folder" from
  VS Code, browsers and other apps opens Galet with the file selected.

## 0.6.0 — Grande barre de recherche et IA qui comprend vos fichiers

- 🔍 **Grande barre de recherche façon Spotlight** (`Ctrl+F` ou 🔍) avec un choix **Simple / IA**,
  résultats immédiats avec miniatures et dossier, Entrée pour ouvrir, Ctrl+Entrée pour afficher dans
  le dossier, « Tout afficher dans Galet ». Réglages → Général : grande barre ou barre classique, et
  mode par défaut (Simple ou IA).
- 🖼️ **Analyser les photos (IA)** (clic droit) : l'IA décrit ce que montrent vos photos (plage,
  montagne, chien…) et la recherche les trouve même si elles s'appellent `IMG_2034.jpg`. Les
  descriptions restent sur votre ordinateur ; seules des copies réduites (512 px) sont envoyées si vous
  utilisez un service en ligne.
- 💻 Recherche **par le sens** dans le code et les documents : « un morceau de code qui lit du JSON »,
  « lecture de Jésus »… Nouveau type **Code**.
- 🇬🇧 Spotlight-style search window (Simple / AI), AI photo analysis for search, meaning-based search
  in code and documents.

## 0.5.2 — Recherche IA qui trouve vraiment

- 🔎 L'IA propose des **mots-clés alternatifs** (synonymes, français/anglais, noms de dossiers :
  « plage » → beach, mer, vacances…) et la recherche regarde aussi **le nom des dossiers** :
  `Vacances/Plage 2024/IMG_0001.jpg` est trouvé.
- 🌐 « Partout » inclut maintenant les **disques réseau (kDrive…) et les disques USB**.
- ⚡ Les résultats s'affichent au fur et à mesure, même quand un disque réseau est lent.
- 💬 Message plus clair quand rien n'est trouvé (Galet ne voit pas le contenu des photos).
- 🇬🇧 AI keywords + folder-name matching, network drives in "Everywhere", progressive results.

## 0.5.1 — Mode IA plus clair, installation depuis la Logithèque

- 🌐 Site web : https://floderail.github.io/galet/
- 📦 Fichier `galet.flatpak` installable par double-clic (dans les versions GitHub).
- 🛍️ Dépôt Flatpak officiel et signé : bouton « Installer dans la Logithèque » sur le site,
  mises à jour automatiques. / Signed Flatpak repository on GitHub Pages, one-click install.
- ✨ **Mode IA** plus clair : activez ✨, écrivez votre phrase, appuyez sur Entrée. Une animation montre
  que l'IA réfléchit, puis une notification indique ce qu'elle a compris. Plus de filtrage pendant la
  frappe. / Clearer AI mode: type a sentence, press Enter; spinner and "AI understood: …" summary.

## 0.5.0 — Choix du fournisseur d'IA

### 🇫🇷 Nouveautés
- 🤖 L'IA peut maintenant utiliser, au choix : **Ollama** (local, par défaut), **Claude**, **Mistral**,
  **Gemini**, **ChatGPT** par clé d'API, ou **Claude Code** / **Gemini CLI** en ligne de commande
  (votre abonnement, sans clé).
- 🔐 Les clés d'API sont rangées dans le **trousseau GNOME**, jamais dans un fichier.
- 🛡️ Avant d'activer un service en ligne, Galet explique ce qui est envoyé et demande votre accord.

### 🇬🇧 What's new
- AI provider choice: Ollama (local, default), Claude, Mistral, Gemini, ChatGPT (API keys in the GNOME
  keyring) or the Claude Code / Gemini CLI tools; privacy confirmation before any online provider.

## 0.4.0 — Recherche dans le contenu, IA locale, Flatpak

### 🇫🇷 Nouveautés
- 🔍 **Recherche dans le contenu** des documents : textes, PDF, LibreOffice, Word/Excel/PowerPoint
  (bouton « document » dans la barre de recherche).
- 🗂️ **Regroupement aussi en vue Icônes** (par type, date ou tag), via le bouton Trier / Grouper.
- 📁 **Dossiers configurables** (Réglages → Dossiers) : couleur du tag appliquée au dossier, couleur
  par défaut de tous les dossiers, palette de couleurs personnalisable.
- 🤖 **IA locale facultative** avec Ollama : recherche en langage naturel et suggestions de tags.
  Désactivée par défaut, rien ne quitte votre ordinateur.
- 🌍 **4 nouvelles langues** : espagnol, allemand, italien, portugais.
- 📦 **Flatpak** : manifeste et fiche AppStream validée, prêts pour Flathub.
- 🐛 Corrigé : la barre du haut pouvait devenir transparente/blanche avec le thème Système ;
  la barre de recherche débordait sur les fenêtres moyennes.

### 🇬🇧 What's new
- Search inside documents, grouping in icon view, configurable folder colours, optional local AI
  (Ollama), Spanish/German/Italian/Portuguese translations, Flatpak packaging, bug fixes.

## 0.3.0 — Logo

- 🇫🇷 Nouveau **logo**, doux et épuré : un galet lavande-bleu avec le contour d'un dossier.
  L'icône apparaît dans le menu des applications, la barre des tâches et « À propos ».
- 🇫🇷 Fenêtre « À propos » : auteur, site [florianderail.fr](https://florianderail.fr), lien vers le code source.
- 🇬🇧 New **logo** and app icon; About window shows the author, website and source code link.

## 0.2.0 — Thèmes et touches Finder

### 🇫🇷 Nouveautés

**Thèmes** (Réglages → Apparence)
- 4 thèmes : **Système** (couleurs de Zorin/GNOME), **macOS** (pastilles rouge-orange-vert à gauche,
  couleurs et police façon Finder), **Windows 11** (boutons rectangulaires, couleurs de l'Explorateur)
  et **Personnalisé** (couleur d'accentuation, position et style des boutons, coins arrondis, police,
  barre latérale teintée).
- Mode **clair, sombre ou automatique** pour chaque thème.

**Fonctions du Finder**
- **Dossiers colorés** : clic droit → « Couleur du dossier » (9 couleurs).
- Bouton **Trier / Grouper** : tri par nom, type, date, taille ou tags.
- Chaque dossier **retient sa présentation** (icônes, liste, colonnes, galerie).
- **Favoris** : « Ajouter à la barre latérale » (clic droit ou glisser sur « Favoris ») et « Retirer ».
- Menu **Aller** et raccourcis (`Ctrl+Maj+H` dossier personnel, `Ctrl+Maj+D` Bureau, `Ctrl+Maj+O` Documents,
  `Ctrl+Alt+L` Téléchargements, `Ctrl+Maj+F` Récents).
- **Fusionner toutes les fenêtres** en onglets ; **glisser un onglet** hors de la fenêtre pour l'ouvrir à part.

### 🇬🇧 What's new

- **Themes**: System, macOS, Windows 11 and Custom, each in light, dark or automatic mode.
- **Coloured folders**, **Sort By** menu, per-folder view memory, add/remove sidebar favourites,
  **Go** menu and shortcuts, **Merge All Windows**, drag tabs out into new windows.

## 0.1.0 — Première version / First release

- Tags de couleur façon Finder, vues Icônes / Liste / Colonnes / Galerie, onglets.
- Coup d'œil, panneau d'aperçu, Lire les informations, miniatures.
- Annuler, renommer sur place, sélection en tapant, dupliquer, conflits de copie, progression.
- Glisser-déposer, dossiers qui s'ouvrent au survol, corbeille (remettre en place, vider).
- Actions rapides : pivoter, convertir, réduire, PDF, ZIP, extraire.
- Recherche dans les sous-dossiers avec filtres et dossiers intelligents.
- Serveurs réseau (SMB, SFTP, FTP, WebDAV), envoi vers le téléphone, réglages, traduction française.
