Objectif : Terminer l'installation de la correction « scrollback tmux confortable » sur CE Mac
(vemao, 10.0.0.4), déjà buildée mais pas encore signée/installée.

Contexte :
- Correction ajoutée côté hpcmultimedia (commit `3524a07`, poussé sur `origin/main`) :
  `Sources/PartageLAN/PartageLAN.swift` complète désormais `~/.tmux.conf` (history-limit 50000 +
  mouse on, idempotent) et applique les réglages en direct (`tmux set -g`) à chaque ouverture de
  Terminal SSH ou Terminal partagé — pour que le scrollback (notamment celui de Claude Code, qui
  écrit en alternate screen) reste consultable même avec beaucoup de texte qui défile.
- Sur vemao, `git pull` + `./build_app.sh` ont déjà été lancés via SSH depuis hpcmultimedia :
  code à jour (fast-forward `e6ea4c2..3524a07`), compilation réussie (`Build complete!`).
- La signature a échoué en session SSH avec `errSecInternalComponent` — limitation connue et
  déjà documentée sur ce projet (trousseau inaccessible hors session graphique). **Ne pas
  contourner par un repli `codesign -s -` ou équivalent** : casserait la stabilité de signature
  (Little Snitch/Gatekeeper redemanderaient l'autorisation).

Tâche :
1. `git status --short` dans `/Users/vemao/Documents/_Programmation/_PartageLAN` — vérifier
   qu'il n'y a aucune modification locale non commitée qui diverge (le seul diff attendu est
   déjà pull/mergé, donc `git status --short` devrait être propre sur `PartageLAN.swift`). Si
   autre chose diverge, s'arrêter et signaler avant de continuer.
2. Lancer `./PartageLAN.command` directement dans cette session (pas via SSH) : il refait
   `git pull` (déjà à jour, sans effet), `setup_signing.sh`, `build_app.sh`, puis installe dans
   `/Applications/PartageLAN.app` et relance le LaunchAgent `fr.vemao.partagelan`.
3. Vérifier le message « Signé avec « PartageLAN Self-Signed » (signature stable). » — si repli
   sur signature ad-hoc (avertissement), s'arrêter et signaler, ne pas continuer.
4. Vérifier que l'app est bien relancée : `pgrep -fl PartageLAN` doit montrer un process récent
   avec le bundle `/Applications/PartageLAN.app`.

Contraintes :
- Pas de commit, pas de push (rien à committer ici, le code est déjà à jour).
- Ne pas régénérer le certificat de signature s'il est déjà présent.
- Ne pas piloter d'autre app via AppleScript/System Events.

Livrable : PartageLAN à jour, signé, installé dans `/Applications`, relancé via le LaunchAgent
sur vemao.

Compte-rendu : créer `prompts-remote/2026-07-13_00h37_install-tmux-comfort-vemao.result.md`
(5-10 lignes) : résultat de `git status --short`, message de signature obtenu, PID de l'instance
relancée.
