Objectif : Finaliser sur CE Mac (vemao, 10.0.0.4) le déploiement de la fonctionnalité « clic
droit sur le panneau distant → Ouvrir dans le Finder », déjà codée et déployée côté
hpcmultimedia (10.0.0.5). Le build via SSH depuis hpcmultimedia a échoué à l'étape de
signature (`codesign` : `errSecInternalComponent`, trousseau de connexion inaccessible dans une
session SSH). En session Claude Code locale (donc trousseau déverrouillé normalement), ça
devrait passer.

Contexte :
- Dépôt : ce dossier (`~/Documents/_Programmation/PartageLAN` sur ce Mac).
- `Sources/PartageLAN/PartageLAN.swift` a déjà été copié depuis hpcmultimedia par scp et contient
  la modif : `PartageEngine.openRemoteFinder(path:)`, le paramètre `onOpenFinder` sur `PaneView`,
  et la nouvelle entrée de menu contextuel « Ouvrir dans le Finder » (panneau distant uniquement).
- Cette modif n'est PAS commitée (ni ici ni sur hpcmultimedia) — c'est volontaire, ne pas
  committer ni push sans demander explicitement à l'utilisateur.
- Le certificat de signature stable « PartageLAN Self-Signed » est déjà installé sur ce Mac
  (confirmé via `security find-identity -p codesigning`).
- `build_app.sh` compile (universel arm64+x86_64), signe et zippe dans `dist/`.

Tâche :
1. Vérifier l'état du dépôt : `git status` + `git diff --stat`. Le diff attendu est
   exactement : `Sources/PartageLAN/PartageLAN.swift | 45 +++++++++++++++++++++++++++++++++++++`
   (1 fichier, 45 insertions, 0 suppression). Si le diff est différent (autre fichier touché,
   nombre de lignes différent, ou diff vide), **arrête-toi et signale-le à l'utilisateur avant de
   continuer** — ne pas écraser un état inattendu.
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

Contraintes :
- Pas de commit, pas de push.
- Ne pas régénérer/modifier le certificat de signature (`setup_signing.sh`).
- Ne pas piloter d'autre app via AppleScript/System Events (cf. note du projet : ça échoue pour
  ce genre d'app agent `LSUIElement`, autorisation « Automatisation » non fiable).
- Ne pas simuler de clic réel dans l'UI de l'app pour « tester » — se limiter à vérifier que le
  process tourne sans crash. L'utilisateur testera lui-même le clic droit.

Livrable : l'app relancée dans `/Applications/PartageLAN.app`, signée avec le certificat stable,
avec la fonctionnalité Finder active. Aucun fichier de code à produire (déjà fait) — uniquement
build + signature + installation + relance.

Compte-rendu : à la fin (succès ou échec), écris un résumé court (5-10 lignes suffisent) dans
`prompts-remote/2026-07-10_07h39_deploy-finder-vemao.result.md` : étapes passées/ratées, message
de `codesign` obtenu, PID final de l'app, tout problème rencontré.
