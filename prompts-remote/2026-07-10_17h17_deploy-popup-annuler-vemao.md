Objectif : Finaliser sur CE Mac (vemao, 10.0.0.4) un tout petit ajustement du popup « Terminal
partagé » déployé juste avant (cf. `2026-07-10_17h04_deploy-popup-terminal-partage-vemao.md` et
son `.result.md`, déjà confirmés OK). Même limitation habituelle : build via SSH depuis
hpcmultimedia échoue à `codesign` ; en session Claude Code locale ça passe normalement (confirmé
deux fois déjà sur cette machine).

Contexte :
- Dépôt : ce dossier (`~/Documents/_Programmation/_PartageLAN` sur ce Mac).
- `Sources/PartageLAN/PartageLAN.swift` déjà copié depuis hpcmultimedia par scp et vérifié
  identique octet pour octet.
- Seul changement depuis le déploiement précédent (125/8) : le `NSAlert` de
  `openSharedTerminal()` a maintenant deux boutons au lieu d'un — « OK » (premier, défaut) et
  « Annuler » (deuxième). Si Annuler est cliqué, la fonction retourne immédiatement sans ouvrir
  Terminal.app (`guard alert.runModal() == .alertFirstButtonReturn else { return }`). Rien
  d'autre modifié.
- tmux et le certificat de signature stable déjà confirmés fonctionnels sur ce Mac — rien à
  vérifier de ce côté.

Tâche :
1. `git status` + `git diff --stat`. Diff attendu sur `Sources/PartageLAN/PartageLAN.swift` :
   exactement 126 insertions(+), 8 deletions(-). `.gitignore` peut apparaître modifié (2 lignes,
   connu, hors périmètre). Si autre chose diverge, **arrête-toi et signale avant de continuer**.
2. `./build_app.sh`. Vérifier « Signé avec « PartageLAN Self-Signed » (signature stable). » — pas
   de repli ad-hoc. Si échec, arrête-toi et signale.
3. `pgrep -fl PartageLAN` (pas `-flx`) pour repérer l'instance en cours, l'arrêter par ce PID
   précis (`kill <pid>`, pas `pkill -x`).
4. `rm -rf /Applications/PartageLAN.app && cp -R dist/PartageLAN.app /Applications/`.
5. `open /Applications/PartageLAN.app`, vérifier via `pgrep -fl PartageLAN` qu'elle tourne après
   2-3 s sans crash.
6. Ne pas toucher au LaunchAgent.

Contraintes :
- Pas de commit, pas de push.
- Ne pas régénérer le certificat de signature.
- Ne pas piloter d'autre app via AppleScript/System Events.
- Ne pas simuler de clic réel dans l'UI — se limiter à vérifier que le process tourne sans crash.

Livrable : l'app relancée dans `/Applications/PartageLAN.app`, signée avec le certificat stable,
popup à deux boutons (OK/Annuler) actif sur « Terminal partagé ».

Compte-rendu : résumé court (5-10 lignes) dans
`prompts-remote/2026-07-10_17h17_deploy-popup-annuler-vemao.result.md` : étapes passées/ratées,
message `codesign`, PID final.
