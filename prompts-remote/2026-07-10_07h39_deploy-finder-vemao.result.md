# Résultat — déploiement clic droit → Ouvrir dans le Finder

**Statut : succès**

1. `git diff --stat` conforme à l'attendu exact : `Sources/PartageLAN/PartageLAN.swift | 45 +++...` (1 fichier, 45 insertions, 0 suppression). Aucun commit/push effectué.
2. `./build_app.sh` : build universel arm64+x86_64 réussi. Message obtenu : « Signé avec « PartageLAN Self-Signed » (signature stable). » — pas de repli ad-hoc. Seul avertissement : deprecation `onChange(of:perform:)` (préexistant, non bloquant) + warnings « Stale file » liés au renommage du dossier projet (`PartageLAN` → `_PartageLAN`), sans impact sur le résultat.
3. Aucune instance PartageLAN trouvée avant install (`pgrep -flx PartageLAN` vide) → pas de kill nécessaire.
4. Installation : `rm -rf /Applications/PartageLAN.app && cp -R dist/PartageLAN.app /Applications/` → OK.
5. Relance : `open /Applications/PartageLAN.app`. Note : `pgrep -flx PartageLAN` (combinaison -f + -x) ne matche pas car il exige une correspondance exacte sur la ligne de commande *complète*, pas juste le nom du process — faux négatif de la commande de vérif suggérée, pas un crash. Confirmé actif via `pgrep -fl -i partagelan` et `ps aux` : **PID final = 912**, `/Applications/PartageLAN.app/Contents/MacOS/PartageLAN`, CPU ~0% (stable, pas de crash-loop).
6. LaunchAgent (`fr.vemao.partagelan.plist`) non touché.

**Livrable** : app relancée dans `/Applications/PartageLAN.app`, signée avec le certificat stable, fonctionnalité Finder incluse (code déjà en place, non re-testée à l'écran — clic droit à valider par l'utilisateur).
