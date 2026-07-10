Résultat — toutes les étapes ont réussi.

1. `git diff --numstat` : `PartageLAN.swift` 126 insertions(+) / 8 deletions(-), `.gitignore`
   2 insertions(+) — conforme à l'attendu. Rien d'inattendu.
2. `./build_app.sh` : build universel arm64+x86_64 OK (seul warning : dépréciation
   `onChange(of:perform:)` préexistante, sans rapport). Message obtenu : « Signé avec « PartageLAN
   Self-Signed » (signature stable). » — pas de repli ad-hoc.
3. Instance précédente repérée via `pgrep -fl PartageLAN` (PID 40449), arrêtée proprement par
   `kill 40449`.
4. Install : `rm -rf /Applications/PartageLAN.app && cp -R dist/PartageLAN.app /Applications/` OK.
5. Relance : `open /Applications/PartageLAN.app`. PID final **42611**, actif après vérification
   (pas de crash).
6. LaunchAgent non touché.

Aucun problème rencontré. Livrable conforme : app relancée dans `/Applications/PartageLAN.app`,
signée avec le certificat stable, popup « Terminal partagé » à deux boutons (OK/Annuler) actif.
Reste à valider côté utilisateur : cliquer sur Annuler pour confirmer que Terminal.app ne s'ouvre
pas dans ce cas.
