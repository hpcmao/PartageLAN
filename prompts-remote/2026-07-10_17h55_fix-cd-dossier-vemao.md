Objectif : Finaliser sur CE Mac (vemao, 10.0.0.4) un deuxième correctif pour « Terminal SSH »,
au-dessus du fix PATH déjà déployé (`2026-07-10_17h38_fix-tmux-path-ssh-vemao.md`, confirmé OK).
Build via SSH échoue toujours à `codesign` ; en session Claude Code locale ça passe (confirmé
plusieurs fois).

Contexte — le bug corrigé :
- L'utilisateur a signalé qu'un clic droit sur un dossier distant → Terminal SSH n'ouvrait pas
  dans ce dossier mais dans `/Users/vemao` (le dossier personnel).
- Cause : `tmux new -A -s partagelan -c "dossier"` ignore `-c` quand la session existe déjà (elle
  rejoint le pane existant tel quel, sans changer son dossier courant). Une session `partagelan`
  traînait depuis un test précédent (créée sans dossier précis) → tous les clics suivants la
  rejoignaient telle quelle, peu importe le dossier demandé.
- Correctif dans `openSSHTerminal(host:dir:)` : la commande distante ne fait plus `tmux new -A`
  mais décompose en `tmux has-session || { tmux new-session -d; sleep 1 }` (création si besoin,
  détachée) puis `tmux send-keys "cd \"dossier\"" Enter` (systématique, respecte TOUJOURS le
  dossier cliqué, que la session soit neuve ou déjà active) puis `tmux attach`. Le `sleep 1`
  n'intervient que sur la branche création (pas sur une ré-attache, qui reste instantanée) — sans
  lui, une race condition fait que le `cd` envoyé juste après la création d'un nouveau pane est
  perdu (le shell n'a pas fini de démarrer). Décision utilisateur : le `cd` est **systématique**
  (pas de mode « une fenêtre par dossier », option écartée pour rester simple — un seul terminal
  partagé suffit pour l'usage actuel).
- Reproduit et vérifié par SSH direct (hors app), dans les deux cas (création ET ré-attache),
  AVANT d'écrire le correctif dans le code.
- `Sources/PartageLAN/PartageLAN.swift` déjà copié depuis hpcmultimedia par scp, vérifié
  identique octet pour octet.
- Au passage, la session `partagelan` qui traînait sur vemao (avec une invite Claude Code en
  attente dedans) a été détruite avec l'accord explicite de l'utilisateur avant ce déploiement —
  rien à faire de ce côté, c'est déjà fait.

Tâche :
1. `git status` + `git diff --stat`. Diff attendu sur `Sources/PartageLAN/PartageLAN.swift` :
   exactement 19 insertions(+), 4 deletions(-) (au-dessus du fix PATH déjà présent). `.gitignore`
   peut apparaître modifié (2 lignes, connu, hors périmètre). Si autre chose diverge,
   **arrête-toi et signale avant de continuer**.
2. `./build_app.sh`. Vérifier « Signé avec « PartageLAN Self-Signed » (signature stable). ».
   Si échec de signature, arrête-toi et signale.
3. `pgrep -fl PartageLAN` (pas `-flx`), arrêter l'instance en cours par ce PID précis
   (`kill <pid>`, pas `pkill -x`).
4. `rm -rf /Applications/PartageLAN.app && cp -R dist/PartageLAN.app /Applications/`.
5. `open /Applications/PartageLAN.app`, vérifier via `pgrep -fl PartageLAN` qu'elle tourne après
   2-3 s sans crash.
6. Ne pas toucher au LaunchAgent.
7. Optionnel (bonus) : rejouer le test hors UI pour confirmer (adapter l'IP/dossier si besoin) :
   ```
   ssh hpcmultimedia@10.0.0.5 'export PATH="/opt/local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"; tmux kill-session -t partagelan 2>/dev/null; tmux has-session -t partagelan 2>/dev/null || { tmux new-session -d -s partagelan; sleep 1; }; tmux send-keys -t partagelan "cd \"/Users/hpcmultimedia\"" Enter'
   sleep 0.5
   ssh hpcmultimedia@10.0.0.5 'export PATH="/opt/local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"; tmux display-message -p -t partagelan "#{pane_current_path}"'
   ```
   doit afficher `/Users/hpcmultimedia`. Nettoyer la session de test ensuite
   (`tmux kill-session -t partagelan`) si ce test est fait.

Contraintes :
- Pas de commit, pas de push (l'utilisateur committera lui-même depuis hpcmultimedia).
- Ne pas régénérer le certificat de signature.
- Ne pas piloter d'autre app via AppleScript/System Events.
- Ne pas simuler de clic réel dans l'UI — se limiter à vérifier que le process tourne sans crash
  (+ le test optionnel hors UI si fait).

Livrable : l'app relancée dans `/Applications/PartageLAN.app`, signée avec le certificat stable,
avec le correctif « cd systématique » actif sur « Terminal SSH ».

Compte-rendu : résumé court (5-10 lignes) dans
`prompts-remote/2026-07-10_17h55_fix-cd-dossier-vemao.result.md` : étapes passées/ratées, message
`codesign`, PID final, résultat du test optionnel si fait.
