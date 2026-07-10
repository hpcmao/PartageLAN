Objectif : Finaliser sur CE Mac (vemao, 10.0.0.4) le déploiement de la fonctionnalité
« Terminal partagé » (tmux), déjà codée et déployée côté hpcmultimedia (10.0.0.5). Le build via
SSH depuis hpcmultimedia échoue systématiquement à l'étape de signature (`codesign` :
`errSecInternalComponent`, trousseau de connexion inaccessible dans une session SSH). En session
Claude Code locale (donc trousseau déverrouillé normalement), ça devrait passer.

Contexte :
- Dépôt : ce dossier (`~/Documents/_Programmation/_PartageLAN` sur ce Mac).
- `Sources/PartageLAN/PartageLAN.swift` a déjà été copié depuis hpcmultimedia par scp et vérifié
  identique octet pour octet à la version de hpcmultimedia (diff vide entre les deux fichiers).
  Contient deux fonctionnalités cumulées, aucune commitée nulle part :
  1. Clic droit distant → Finder (SMB), déjà déployée ici lors d'une session précédente.
  2. Terminal partagé (nouvelle, objet de cette tâche) : `PartageEngine.openSSHTerminal(host:dir:)`
     ouvre désormais une session tmux partagée (`tmux new -A -s partagelan`) au lieu d'un shell
     simple ; nouvelle fonction `openSharedTerminal()` ouvre Terminal.app en local (sans SSH) et
     rejoint la même session tmux ; nouveau bouton « Terminal partagé » (icône `person.2`) dans la
     barre du bas, à côté de « Terminal SSH ». But : un Terminal SSH ouvert vers cette machine
     depuis hpcmultimedia (ou l'inverse) devient visible/pilotable aussi en local sur la machine
     ciblée, via ce bouton.
- tmux est déjà installé et vérifié fonctionnel sur ce Mac (`/opt/local/bin/tmux`, version 3.7b,
  installé via `sudo port install tmux`) — pas besoin de l'installer. Note : `command -v tmux`
  seul peut donner un faux négatif en session SSH non-interactive sur cette machine (PATH minimal,
  sans `/opt/local/bin`) ; en session Claude Code locale normale ça ne devrait pas arriver, mais si
  jamais `tmux` semble introuvable, vérifier `/opt/local/bin/tmux` avant de conclure à une absence.
- Le certificat de signature stable « PartageLAN Self-Signed » est déjà installé sur ce Mac
  (confirmé lors du déploiement Finder précédent).
- `build_app.sh` compile (universel arm64+x86_64), signe et zippe dans `dist/`.

Tâche :
1. Vérifier l'état du dépôt : `git status` + `git diff --stat`. Le diff attendu sur
   `Sources/PartageLAN/PartageLAN.swift` est exactement : 117 insertions(+), 8 deletions(-). Le
   `.gitignore` peut apparaître modifié (2 lignes, `docs_apprentissage/` et `Compte rendu/` —
   connu, laissé tel quel depuis la session précédente, hors périmètre). Si autre chose diverge
   (fichier inattendu, nombre de lignes différent sur PartageLAN.swift), **arrête-toi et
   signale-le à l'utilisateur avant de continuer** — ne pas écraser un état inattendu.
2. Lancer `./build_app.sh`. Vérifier que la sortie contient bien
   « Signé avec « PartageLAN Self-Signed » (signature stable). » — PAS le message de repli
   ad-hoc. Si ça repart en ad-hoc ou que `codesign` échoue encore, arrête-toi et signale (ne pas
   forcer une signature ad-hoc à la place, ça casserait les autorisations Little Snitch déjà
   accordées sur ce Mac).
3. Repérer l'instance PartageLAN en cours si elle tourne (`pgrep -x PartageLAN`), l'arrêter
   proprement par ce PID précis (`kill <pid>`, pas `pkill -x` en aveugle, pas `kill -9` sauf si
   elle ne s'arrête pas après quelques secondes).
4. Installer : `rm -rf /Applications/PartageLAN.app && cp -R dist/PartageLAN.app /Applications/`.
5. Relancer : `open /Applications/PartageLAN.app`, vérifier via `pgrep -flx PartageLAN` qu'elle
   tourne après 2-3 s (pas de crash immédiat).
6. Ne pas toucher au LaunchAgent (`~/Library/LaunchAgents/fr.vemao.partagelan.plist`) — déjà
   configuré correctement, pas besoin de le recréer.
7. Optionnel (bonus, pas obligatoire) : un test fonctionnel de tmux lui-même hors UI, pour
   confort — créer une session détachée, y écrire quelque chose, la relire, la détruire :
   `tmux new-session -d -s verif && tmux send-keys -t verif 'echo test' Enter && sleep 0.3 && tmux capture-pane -t verif -p; tmux kill-session -t verif`.
   Ne pas laisser de session `verif` derrière soi si ce test est fait.

Contraintes :
- Pas de commit, pas de push.
- Ne pas régénérer/modifier le certificat de signature (`setup_signing.sh`).
- Ne pas piloter d'autre app via AppleScript/System Events (cf. note du projet : ça échoue pour
  ce genre d'app agent `LSUIElement`, autorisation « Automatisation » non fiable).
- Ne pas simuler de clic réel dans l'UI de l'app pour « tester » — se limiter à vérifier que le
  process tourne sans crash (+ le test tmux optionnel hors UI si fait). L'utilisateur testera
  lui-même les boutons SSH/Terminal partagé.

Livrable : l'app relancée dans `/Applications/PartageLAN.app`, signée avec le certificat stable,
avec les deux fonctionnalités (Finder + Terminal partagé) actives. Aucun fichier de code à
produire (déjà fait) — uniquement build + signature + installation + relance.

Compte-rendu : à la fin (succès ou échec), écris un résumé court (5-10 lignes suffisent) dans
`prompts-remote/2026-07-10_16h38_deploy-terminal-partage-vemao.result.md` : étapes passées/ratées,
message de `codesign` obtenu, PID final de l'app, résultat du test tmux optionnel si fait, tout
problème rencontré.
