# Nouveautés / Changelog

Galet — logiciel libre et open source de [Florian Dérail](https://florianderail.fr).

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
