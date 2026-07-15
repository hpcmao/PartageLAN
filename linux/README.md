# PartageLAN — client Linux (`haikubuntu`)

Portage Linux de l'app macOS PartageLAN. Parle le **même protocole TCP** (port **7365**,
framing `[UInt32 big-endian longueur][JSON][octets]`, types `clip/file/ping/pong/ls/lsr/get/err`)
et **reproduit l'interface à deux panneaux** (façon Transmit). Écrit en **Python**, sur la
base du portage Windows (`windows/`), adapté au bureau Linux (testé sous Ubuntu MATE, X11).

- `partagelan.py` — cœur du protocole + version **ligne de commande** (stdlib seule).
- `partagelan_tray.py` — **application de fond** : icône dans la zone de notification +
  fenêtre à deux panneaux + écoute permanente + lancement au démarrage.
- `install.sh` — installation en un geste (paquets, venv, lanceurs, pare-feu, lancement).
- `PartageLAN.sh` — lanceur double-clic (installe au premier lancement).

## Installer

```bash
cd PartageLAN/linux
./install.sh
```

Le script fait tout :

1. **Paquets système** manquants via apt : `python3-tk` (interface), `xclip` (presse-papier).
   Nécessite sudo → activer le profil **« Install »** dans **SudoManager** (ou saisir le
   mot de passe).
2. **Environnement Python** `.venv` (avec accès aux paquets système) + `pystray`,
   `pillow`, `tkinterdnd2` — sans sudo.
3. **Lanceur** dans le menu Applications + **démarrage automatique**
   (`~/.config/autostart/PartageLAN.desktop`, désactivable depuis le menu de l'icône).
4. **Pare-feu** : `ufw allow 7365/tcp` (si ufw est actif) → profil **« Admin »** de
   SudoManager, sinon la commande à lancer est affichée. Sans cette règle, le Mac ne
   peut pas nous joindre (nos envois vers le Mac marchent quand même).
5. Lance l'app : icône **⬅➡** près de l'horloge (**bleue** = le Mac répond ·
   **grise** = injoignable). **Clic gauche** = ouvre la fenêtre **et** le menu ;
   clic droit = menu. Relancer l'app (menu, lanceur ou `PartageLAN.sh`) quand elle
   tourne déjà fait apparaître sa fenêtre.

Réglages persistés dans `~/.config/PartageLAN/config.json` : chemins des deux
panneaux, IP du pair, thème, taille **et position** de la fenêtre — **écriture
immédiate** à chaque changement (robuste au crash, comme l'app Mac).

## La fenêtre à deux panneaux

Réplique de l'app Mac (mêmes fonctions que le client Windows) :

- **Barre haute** : sélecteur **Presse-papier** (Les 2 sens / Envoi seul / Réception seule /
  Coupé — synchro **bidirectionnelle** avec anti-écho, sondage 0,6 s) et **Thème**
  (9 thèmes ; « Système » suit le thème sombre/clair du bureau via gsettings).
- **Panneau gauche « Machine locale — haikubuntu »** : navigation dans le disque Linux.
  Listes triées par **date de modification** (plus récent en premier), colonne
  « Modifié » affichée. Le panneau distant est trié pareil quand le pair fournit les
  dates (champ `mtime` ajouté aux `lsr` ; l'app Mac ne l'envoie pas encore → ordre du Mac).
- **Panneau droit « Machine distante — vemao »** : navigation dans le Mac (via le
  protocole), champ **IP**, **Tester**, **Scanner** (menu des machines détectées sur le /24).
- Boutons **→** / **←** au centre : copier la sélection vers le dossier affiché en face
  (noms dédoublonnés ; dossiers non gérés — zipper d'abord).
- **Bas** : statut « Ici : haikubuntu… à l'écoute », ligne **SSH** (Terminal SSH /
  Terminal partagé `tmux -s partagelan`), **journal horodaté** copiable. Les fichiers
  reçus arrivent dans **le dossier affiché à gauche** (bouton **Ouvrir**) et le
  panneau se rafraîchit à la réception. Affichage agrandi (textes et listes ×1,5).
- **Glisser-déposer** depuis Caja : panneau **droit** → envoie au Mac ; panneau
  **gauche** → copie locale. **Clic droit** : envoyer/récupérer, ouvrir un dossier
  dans l'explorateur de fichiers (local, ou **SMB** pour un dossier du Mac :
  `/Users/vemao/…` → `smb://IP/vemao/…`, Partage de fichiers macOS requis),
  afficher dans le dossier parent, Terminal SSH ici, actualiser.
  **Sélection à la souris** (glisser, Ctrl/Maj + clic). Double-clic : dossier → entrer ;
  fichier distant → le récupérer.

Le presse-papier passe par **xclip** (ou wl-clipboard sous Wayland, xsel, GTK) ; à défaut,
repli sur le presse-papier Tk interne. Une trame `file` entrante **honore le dossier de
destination** demandé s'il existe (comme l'app Mac), sinon arrive dans le dossier affiché
à gauche.

## Ligne de commande (`partagelan.py`)

```bash
python3 partagelan.py ping                       # présence du Mac (10.0.0.4 par défaut)
python3 partagelan.py scan                       # machines PartageLAN du /24
python3 partagelan.py ls ~                       # lister l'accueil du Mac
python3 partagelan.py pull ~/Documents/note.txt  # Mac -> Linux (Téléchargements)
python3 partagelan.py push ~/fichier.zip         # Linux -> Mac
python3 partagelan.py send-clip "texte"          # presse-papier -> Mac
python3 partagelan.py listen                     # pair complet (recevoir du Mac)
python3 partagelan.py --ip 10.0.0.7 ping         # viser une autre IP
```

`listen` fait de haikubuntu un pair complet (répond aux pings, reçoit
fichiers/presse-papier, sert `ls`/`get`). Un chemin macOS (`/Users/...`) ou Windows
(`C:\...`) hérité du multiboot **retombe sur l'accueil** `/home/haikubuntu` (`dir_for_ls`)
au lieu d'une erreur.

## Repères réseau (multiboot)

| Machine physique | Nom (selon l'OS booté)  | IP       | PartageLAN                        |
|------------------|-------------------------|----------|-----------------------------------|
| Cet ordi         | **haikubuntu** (Linux)  | 10.0.0.5 | ✅ ce portage                     |
| Cet ordi         | winjeux (Windows)       | 10.0.0.5 | ✅ portage `windows/`             |
| Cet ordi         | hpcmultimedia (macOS)   | 10.0.0.5 | ✅ app SwiftUI native             |
| Autre            | vemao (macOS)           | 10.0.0.4 | pilote / app native, cible défaut |

Un seul OS démarré à la fois sur 10.0.0.5 → pas de conflit d'IP. Depuis le Mac `vemao`,
prévoir l'alias SSH `haikubuntu` avec `HostKeyAlias` dans `~/.ssh/config` (voir
`windows/README.md`, remplacer `pclinux` par `haikubuntu`).

## SSH : le Mac entre dans haikubuntu (à activer)

```bash
sudo apt install -y openssh-server && sudo systemctl enable --now ssh
sudo ufw allow from 10.0.0.0/24 to any port 22 proto tcp
```

(profils SudoManager : « Install » puis « Admin »). Ensuite depuis vemao :
`ssh-copy-id haikubuntu@10.0.0.5`. Le bouton « Terminal partagé » suppose `tmux`
côté machine distante (présent sur le Mac).

## Désactiver le lancement automatique

Menu de l'icône → décocher **Lancer au démarrage**, ou :
`rm ~/.config/autostart/PartageLAN.desktop`
