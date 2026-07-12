# PartageLAN

App macOS (SwiftUI) à ouvrir sur **les deux** machines (10.0.0.4 `vemao` et 10.0.0.5
`hpcmultimedia`). Fenêtre type Transmit : deux panneaux de navigation + presse-papier partagé.

## Fonctions

- **Deux panneaux** : « Machine locale » et « Machine distante », chacun avec son compte,
  son IP et son système affichés. Navigation complète des deux côtés : double-clic pour
  entrer dans un dossier, ⬆ dossier parent, chemin éditable (Entrée pour y aller), ⟳ rafraîchir.
- **Copie de fichiers dans les deux sens** : sélection (clic, ⌘/⇧ + clic, ou glisser la souris
  façon Finder pour sélectionner plusieurs éléments) puis
  bouton **→** (local → dossier distant affiché) ou **←** (distant → dossier local affiché).
  Double-clic sur un fichier distant = le récupérer. Glisser-déposer des fichiers du Finder
  sur le panneau distant = les envoyer dans le dossier distant affiché. Noms dédoublonnés.
  Dossiers non gérés (zipper d'abord).
- **Presse-papier partagé** (texte) : Les 2 sens / Envoi seul / Réception seule / Coupé
  (sondage 0,6 s, anti-écho).
- **Scan réseau** : bouton **Scanner** dans l'en-tête du panneau distant. Sonde tout le
  sous-réseau /24 local (ping sur 7365), liste les Macs PartageLAN détectés dans un menu
  déroulant (compte · IP · système), un clic sélectionne l'IP. Sélection automatique si un
  seul Mac répond.
- **Icône barre de menus** (⬅➡ en haut de l'écran) : statut du pair + actions rapides
  (ouvrir la fenêtre, tester, scanner, quitter). L'app tourne en **arrière-plan** (agent) :
  pas d'icône dans le Dock, fenêtre ouverte à la demande depuis l'icône.
- **Terminal SSH** : champs `user@hôte` + `dossier distant` (mémorisés) et bouton
  **Terminal SSH** qui ouvre Terminal.app en `ssh -t` et se place dans le dossier indiqué.
- **Dossier de réception** configurable : y arrivent les fichiers poussés spontanément
  par l'autre machine (par défaut ~/Downloads).
- **Persistance** : chemins des deux panneaux, dossier de réception, IP du pair, thème et
  géométrie de fenêtre conservés entre les sessions (écriture immédiate, robuste au crash).
- **Thèmes** : Système, Clair, Sombre, Océan, Sépia, Nord, Dracula, Solarisé clair, Contraste
  élevé. Fenêtre redimensionnable, tooltips partout, textes copiables (journal copiable d'un clic).

## Fonctionnement

Chaque instance écoute en TCP sur le port **7365** et parle à l'IP « Autre machine »
(pré-remplie 10.0.0.4 ↔ 10.0.0.5, mémorisée). Le port 7365 est un simple choix (port haut
libre) — modifiable via la constante `portNumber` (même valeur des deux côtés). Protocole :
trame `[longueur UInt32 big-endian][JSON méta][octets]` ; types : clip, file, ping/pong,
ls/lsr, get, err. Le pong et le lsr transportent compte + OS de la machine. Le partage lui-même
n'utilise pas SSH (le bouton Terminal SSH est un raccourci indépendant).
⚠️ Les deux machines doivent avoir la même version de l'app.

## Installer / mettre à jour : PartageLAN.command

Un seul geste, identique sur les deux machines (outils Swift requis :
`xcode-select --install` si absents) :

```bash
git clone https://github.com/hpcmao/PartageLAN.git
open PartageLAN/PartageLAN.command      # ou double-clic dans le Finder
```

Le script fait tout : `git pull` (ou clonage dans ~/PartageLAN s'il est lancé seul),
création d'un **certificat de signature stable** (`setup_signing.sh`, une fois par Mac),
compilation (`build_app.sh` → app universelle arm64+x86_64), installation de
**PartageLAN.app** et de **PartageLAN.command** dans /Applications, installation du
**LaunchAgent** `fr.vemao.partagelan` (lancement automatique à chaque session), puis
lancement. Il mémorise l'emplacement du dépôt dans `~/.partagelan_repo`.

**Mise à jour future** : double-clic sur `/Applications/PartageLAN.command`.

### Signature stable (Little Snitch / Gatekeeper)

L'app est signée avec un **certificat auto-signé stable** (`PartageLAN Self-Signed`, créé par
`setup_signing.sh` dans le trousseau login). But : garder une signature **constante entre
rebuilds** pour que **Little Snitch** (et Gatekeeper) conservent leurs règles au lieu de
redemander une autorisation à chaque compilation. À défaut de certificat, repli sur ad-hoc.

- Au tout 1ᵉ build après création du certif, macOS peut demander d'autoriser codesign à
  utiliser la clé → cliquer **« Toujours autoriser »** (une fois).
- La 1ʳᵉ fois seulement, autoriser **PartageLAN** dans **Little Snitch** (connexions
  entrantes + sortantes sur le réseau local). Ensuite, plus de re-blocage aux mises à jour.
- Le certificat doit être créé **localement** sur chaque Mac (le trousseau n'est pas
  accessible via SSH) : lancer `./setup_signing.sh` sur place, ou simplement le `.command`.

Désactiver le lancement automatique :
`launchctl bootout gui/$(id -u)/fr.vemao.partagelan && rm ~/Library/LaunchAgents/fr.vemao.partagelan.plist`
