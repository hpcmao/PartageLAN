# PartageLAN — client Windows (`winjeux`)

Portage Windows de l'app macOS PartageLAN. Parle le **même protocole TCP** (port **7365**,
framing `[UInt32 big-endian longueur][JSON][octets]`, types `clip/file/ping/pong/ls/lsr/get/err`)
et **reproduit l'interface à deux panneaux** (façon Transmit). Écrit en **Python** (l'app
SwiftUI d'origine ne tourne que sur macOS).

- `partagelan.py` — cœur du protocole + version **ligne de commande**.
- `partagelan_tray.py` — **application de fond** : icône dans la zone de notification +
  fenêtre à deux panneaux + écoute permanente + lancement au démarrage.
- `PartageLAN.bat` — lanceur double-clic (silencieux, sans console).

## Prérequis

- **Python 3** (installé : 3.13). Vérifier : `python --version`
- Dépendances de l'app de fond : `pip install pystray Pillow tkinterdnd2` (déjà fait).
- Sur le Mac : **PartageLAN.app** ouverte et autorisée dans Little Snitch / le pare-feu.

## Application de fond (recommandé)

Double-clic sur **`PartageLAN.bat`** → une **icône** apparaît près de l'horloge (lancement
silencieux via `pythonw`, une seule instance à la fois).

- **Clic gauche** sur l'icône → ouvre la fenêtre **et** affiche le menu ; **clic droit** → menu.
- Icône **bleue** = le Mac répond · **grise** = injoignable.
- **Lancement au démarrage** : activé (clé registre `HKCU\…\Run`) ; se désactive via le menu.
- **Réglages** persistés dans `%APPDATA%\PartageLAN\config.json`.

### La fenêtre à deux panneaux

Réplique de l'app Mac :

- **Barre haute** : sélecteur **Presse-papier** (Les 2 sens / Envoi seul / Réception seule /
  Coupé — synchro **bidirectionnelle** avec anti-écho) et sélecteur **Thème** (9 thèmes :
  Système, Clair, Sombre, Océan, Sépia, Nord, Dracula, Solarisé clair, Contraste élevé).
- **Panneau gauche « Machine locale — winjeux »** : navigation dans le disque Windows.
- **Panneau droit « Machine distante — vemao »** : navigation dans le Mac (via le protocole),
  avec champ **IP**, bouton **Tester**, et **Scanner** (menu des machines détectées sur le /24).
- Boutons **→** / **←** au centre : copier la sélection d'un panneau vers le dossier affiché
  de l'autre (noms dédoublonnés ; dossiers non gérés).
- **Bas** : dossier de réception (**Choisir…/Ouvrir**), statut « Ici : winjeux… à l'écoute »,
  ligne **SSH** (Terminal SSH / Terminal partagé), et **journal horodaté** copiable.

Fonctions de manipulation (comme sur le Mac) :

- **Glisser-déposer** depuis l'Explorateur : sur le panneau **droit** → envoie au Mac ; sur le
  panneau **gauche** → copie dans le dossier local (via `tkinterdnd2`).
- **Menu clic-droit** sur un élément : envoyer/récupérer, ouvrir, Terminal SSH ici, actualiser.
- **Sélection à la souris** : glisser pour sélectionner une plage (+ Ctrl/Maj + clic).
- Double-clic : dossier → entrer ; fichier distant → le récupérer.

> Le presse-papier utilise l'**API Win32 native** (ctypes) — aucune fenêtre parasite.

## Ligne de commande (`partagelan.py`)

```powershell
python partagelan.py ping                      # présence du Mac (10.0.0.4 par défaut)
python partagelan.py scan                       # machines PartageLAN du /24
python partagelan.py ls ~                        # lister l'accueil du Mac
python partagelan.py pull ~/Documents/note.txt   # Mac -> Windows (Téléchargements)
python partagelan.py push "C:\...\fichier.zip"   # Windows -> Mac
python partagelan.py send-clip "texte"          # presse-papier -> Mac
python partagelan.py listen                      # pair complet (recevoir du Mac)
python partagelan.py --ip 10.0.0.7 ping         # viser une autre IP
```

`listen` fait de winjeux un pair complet (répond aux pings, reçoit fichiers/presse-papier,
sert `ls`/`get`). Un chemin macOS hérité (`/Users/...`) inexistant sous Windows **retombe sur
l'accueil** `C:\Users\winjeux` (`dir_for_ls`) au lieu d'une erreur.

## SSH : le Mac entre dans Windows

`winjeux` fait tourner un **serveur OpenSSH** (installé le 13/07/2026) :

- Service `sshd` en **démarrage automatique**, **shell par défaut = PowerShell**.
- **Pare-feu** : port 22 autorisé en entrée, **restreint au réseau local** (`LocalSubnet`),
  sur tous les profils (la règle par défaut n'était active qu'en profil *Privé* ; le réseau
  étant *Public*, il a fallu l'étendre — sinon `Operation timed out`).
- `winjeux` est **administrateur** ⇒ les clés publiques autorisées vont dans
  `C:\ProgramData\ssh\administrators_authorized_keys` (ACL stricte SYSTEM + Administrateurs),
  **pas** dans `~/.ssh`. Le compte **n'a pas de mot de passe** ⇒ **authentification par clé
  obligatoire**.

> ⚠️ Le bouton « Terminal SSH » de l'app **Mac** injecte des commandes **tmux** (absentes sous
> Windows). Pour un shell Windows propre, faire un `ssh winjeux@10.0.0.5` **normal** depuis le
> Terminal du Mac.

### Multi-boot : `~/.ssh/config` avec `HostKeyAlias`

Cet ordinateur est en **triple-boot** (macOS `hpcmultimedia`, Windows `winjeux`, Linux
`pclinux`) — tous en **10.0.0.5**, un seul démarré à la fois. Chaque OS a une **clé d'hôte SSH
différente** → conflit `known_hosts` à chaque changement. La solution : un alias par OS avec
`HostKeyAlias` (chaque alias mémorise sa propre clé). Sur le Mac `vemao`, dans `~/.ssh/config` :

```sshconfig
Host winjeux
    HostName 10.0.0.5
    User winjeux
    HostKeyAlias winjeux

Host hpcmultimedia
    HostName 10.0.0.5
    User <compte-macos>
    HostKeyAlias hpcmultimedia

Host pclinux
    HostName 10.0.0.5
    User <compte-linux>
    HostKeyAlias pclinux
```

Ensuite : `ssh winjeux` / `ssh hpcmultimedia` / `ssh pclinux` — sans conflit, sans mot de passe
(après autorisation de la clé de vemao sur chaque OS). Voir `ETAT_13-07-2026.md` pour le reste à faire.

## Repères réseau

| Machine physique | Nom (selon l'OS booté)  | IP       | SSH entrant                          |
|------------------|-------------------------|----------|--------------------------------------|
| Cet ordi         | **winjeux** (Windows)   | 10.0.0.5 | ✅ OpenSSH (clé)                     |
| Cet ordi         | hpcmultimedia (macOS)   | 10.0.0.5 | ⏳ à activer (Session à distance)    |
| Cet ordi         | pclinux (Linux)         | 10.0.0.5 | ⏳ à activer (openssh-server)        |
| Autre            | vemao (macOS)           | 10.0.0.4 | pilote / app PartageLAN native      |

Triple-boot : un seul OS démarré à la fois sur 10.0.0.5 → aucun conflit d'IP. `vemao` (10.0.0.4)
est la machine qui pilote et la cible par défaut du client.
