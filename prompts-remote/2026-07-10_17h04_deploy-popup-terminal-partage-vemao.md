Objectif : Finaliser sur CE Mac (vemao, 10.0.0.4) le déploiement d'un petit ajout au « Terminal
partagé » (déjà déployé ici juste avant, cf. `2026-07-10_16h38_deploy-terminal-partage-vemao.md`
et son `.result.md`). Même limitation que d'habitude : le build via SSH depuis hpcmultimedia
échoue à l'étape `codesign` (trousseau inaccessible en session SSH) ; en session Claude Code
locale ça passe normalement (confirmé lors du déploiement précédent).

Contexte :
- Dépôt : ce dossier (`~/Documents/_Programmation/_PartageLAN` sur ce Mac).
- `Sources/PartageLAN/PartageLAN.swift` a déjà été copié depuis hpcmultimedia par scp et vérifié
  identique octet pour octet à la version de hpcmultimedia.
- Seul changement depuis le déploiement précédent (117/8) : `openSharedTerminal()` affiche
  maintenant un `NSAlert` explicatif (titre « Terminal partagé », un bouton « Ouvrir le
  terminal ») avant d'ouvrir Terminal.app, pour expliquer à l'utilisateur ce que fait le bouton.
  Rien d'autre modifié.
- tmux déjà installé et fonctionnel sur ce Mac (`/opt/local/bin/tmux`, 3.7b) — rien à faire de ce
  côté.
- Certificat de signature stable « PartageLAN Self-Signed » déjà confirmé fonctionnel en session
  locale lors du déploiement précédent.

Tâche :
1. Vérifier l'état du dépôt : `git status` + `git diff --stat`. Diff attendu sur
   `Sources/PartageLAN/PartageLAN.swift` : exactement 125 insertions(+), 8 deletions(-). Le
   `.gitignore` peut apparaître modifié (2 lignes, connu, hors périmètre). Si autre chose diverge,
   **arrête-toi et signale-le à l'utilisateur avant de continuer**.
2. `./build_app.sh`. Vérifier le message « Signé avec « PartageLAN Self-Signed » (signature
   stable). » — pas le repli ad-hoc. Si échec de signature, arrête-toi et signale (ne pas forcer
   une signature ad-hoc).
3. Repérer l'instance en cours (`pgrep -fl PartageLAN` — PAS `-flx`, le nom de process complet
   contient le chemin donc le match exact échoue, cf. `.result.md` précédent), l'arrêter par ce
   PID précis (`kill <pid>`, pas `pkill -x` en aveugle).
4. Installer : `rm -rf /Applications/PartageLAN.app && cp -R dist/PartageLAN.app /Applications/`.
5. Relancer : `open /Applications/PartageLAN.app`, vérifier via `pgrep -fl PartageLAN` qu'elle
   tourne après 2-3 s sans crash.
6. Ne pas toucher au LaunchAgent.

Contraintes :
- Pas de commit, pas de push.
- Ne pas régénérer le certificat de signature.
- Ne pas piloter d'autre app via AppleScript/System Events.
- Ne pas simuler de clic réel dans l'UI (donc pas moyen de voir le `NSAlert` s'afficher
  réellement depuis cette session) — se limiter à vérifier que le process tourne sans crash.
  L'utilisateur validera lui-même le popup en cliquant sur le bouton.

Livrable : l'app relancée dans `/Applications/PartageLAN.app`, signée avec le certificat stable,
avec le popup explicatif actif sur « Terminal partagé ».

Compte-rendu : résumé court (5-10 lignes) dans
`prompts-remote/2026-07-10_17h04_deploy-popup-terminal-partage-vemao.result.md` : étapes
passées/ratées, message `codesign`, PID final.
