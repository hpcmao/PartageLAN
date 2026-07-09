# PartageLAN

App macOS (SwiftUI) à ouvrir sur **les deux** machines (10.0.0.4 `vemao` et 10.0.0.5
`hpcmultimedia`). Fenêtre type Transmit : deux panneaux de navigation + presse-papier partagé.

## Fonctions

- **Deux panneaux** : « Machine locale » et « Machine distante », chacun avec son compte,
  son IP et son système affichés. Navigation complète des deux côtés : double-clic pour
  entrer dans un dossier, ⬆ dossier parent, chemin éditable (Entrée pour y aller), ⟳ rafraîchir.
- **Copie de fichiers dans les deux sens** : sélection (⌘-clic pour multiple) puis
  bouton **→** (local → dossier distant affiché) ou **←** (distant → dossier local affiché).
  Double-clic sur un fichier distant = le récupérer. Glisser-déposer des fichiers du Finder
  sur le panneau distant = les envoyer dans le dossier distant affiché. Noms dédoublonnés.
  Dossiers non gérés (zipper d'abord).
- **Presse-papier partagé** (texte) : Les 2 sens / Envoi seul / Réception seule / Coupé
  (sondage 0,6 s, anti-écho).
- **Dossier de réception** configurable : y arrivent les fichiers poussés spontanément
  par l'autre machine (par défaut ~/Downloads).
- **Thèmes** : Système, Clair, Sombre, Océan, Sépia. Fenêtre redimensionnable, tooltips
  partout, textes copiables (journal copiable d'un clic).

## Fonctionnement

Chaque instance écoute en TCP sur le port **7365** et parle à l'IP « Autre machine »
(pré-remplie 10.0.0.4 ↔ 10.0.0.5, mémorisée). Protocole : trame
`[longueur UInt32 big-endian][JSON méta][octets]` ; types : clip, file, ping/pong, ls/lsr, get, err.
Le pong et le lsr transportent compte + OS de la machine. Aucun besoin de SSH.
⚠️ Les deux machines doivent avoir la même version de l'app.

## Fabriquer / installer

```bash
./build_app.sh          # → dist/PartageLAN.app (universel arm64+x86_64) + dist/PartageLAN.zip
```

Sur l'autre machine (terminal local) :

```bash
scp vemao@10.0.0.4:/Users/vemao/Documents/_Programmation/PartageLAN/dist/PartageLAN.zip ~/Desktop/
```

Dézipper (double-clic), remplacer l'ancienne app le cas échéant, ouvrir
(1ʳᵉ fois : clic droit → Ouvrir ; signature ad hoc). Si le pare-feu demande
« accepter les connexions entrantes » → Autoriser.

Lancement automatique : Réglages Système → Général → Ouverture → ajouter PartageLAN.
