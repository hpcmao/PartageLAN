Objectif : Finaliser sur CE Mac (vemao, 10.0.0.4) un correctif de bug pour le Terminal partagé,
déployé côté hpcmultimedia. Même limitation habituelle pour le build : `codesign` échoue en
session SSH, mais passe en session Claude Code locale (confirmé plusieurs fois sur ce Mac).

Contexte — le bug corrigé :
- L'utilisateur a testé un Terminal SSH depuis hpcmultimedia vers vemao (avec un dossier distant)
  et a obtenu `zsh:1: command not found: tmux`, alors que tmux est bien installé sur vemao
  (`/opt/local/bin/tmux`, confirmé plusieurs fois).
- Cause : `ssh host 'commande'` exécute un shell **non-login** côté distant, qui ne source pas
  `~/.zprofile` — donc le PATH n'inclut pas `/opt/local/bin` (MacPorts) ni les emplacements
  Homebrew. C'est le même phénomène que le faux négatif `command -v tmux` déjà rencontré et
  documenté pendant le développement de cette fonctionnalité, mais qui touchait cette fois la
  fonctionnalité réelle, pas juste une vérification.
- Correctif dans `openSSHTerminal(host:dir:)` : la commande SSH distante commence maintenant par
  `export PATH="/opt/local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"; ` avant `tmux new -A -s
  partagelan [...]`. Reproduit et vérifié avant/après par SSH direct (hors app) : `command not
  found` sans le correctif, `tmux 3.7b` fonctionnel avec.
- `Sources/PartageLAN/PartageLAN.swift` déjà copié depuis hpcmultimedia par scp, vérifié
  identique octet pour octet.

Tâche :
1. `git status` + `git diff --stat`. Diff attendu sur `Sources/PartageLAN/PartageLAN.swift` :
   exactement 6 insertions(+), 2 deletions(-) (petit correctif ciblé, appliqué après le commit
   `ee51d6d` déjà pullé sur ce Mac). `.gitignore` peut apparaître modifié (2 lignes, connu, hors
   périmètre). Si autre chose diverge, **arrête-toi et signale avant de continuer**.
2. `./build_app.sh`. Vérifier « Signé avec « PartageLAN Self-Signed » (signature stable). ».
   Si échec de signature, arrête-toi et signale.
3. `pgrep -fl PartageLAN` (pas `-flx`), arrêter l'instance en cours par ce PID précis
   (`kill <pid>`, pas `pkill -x`).
4. `rm -rf /Applications/PartageLAN.app && cp -R dist/PartageLAN.app /Applications/`.
5. `open /Applications/PartageLAN.app`, vérifier via `pgrep -fl PartageLAN` qu'elle tourne après
   2-3 s sans crash.
6. Ne pas toucher au LaunchAgent.
7. Optionnel (bonus) : vérifier que le correctif fonctionne réellement en rejouant la commande
   SSH hors app (pas besoin de cliquer dans l'UI) :
   `ssh -o ConnectTimeout=5 hpcmultimedia@10.0.0.5 'export PATH="/opt/local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"; tmux -V'`
   (adapter l'utilisateur/IP si besoin) doit renvoyer une version tmux, pas "command not found".

Contraintes :
- Pas de commit, pas de push (l'utilisateur committera lui-même depuis hpcmultimedia une fois
  confirmé).
- Ne pas régénérer le certificat de signature.
- Ne pas piloter d'autre app via AppleScript/System Events.
- Ne pas simuler de clic réel dans l'UI — se limiter à vérifier que le process tourne sans crash
  (+ le test SSH optionnel hors UI si fait).

Livrable : l'app relancée dans `/Applications/PartageLAN.app`, signée avec le certificat stable,
avec le correctif PATH actif sur « Terminal SSH ».

Compte-rendu : résumé court (5-10 lignes) dans
`prompts-remote/2026-07-10_17h38_fix-tmux-path-ssh-vemao.result.md` : étapes passées/ratées,
message `codesign`, PID final, résultat du test optionnel si fait.
