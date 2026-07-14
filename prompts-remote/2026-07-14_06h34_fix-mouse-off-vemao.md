Objectif : Déployer sur CE Mac (vemao, 10.0.0.4) le correctif qui rétablit le copier natif à la
souris dans tmux (au CLI en SSH ET dans le Terminal partagé), en désactivant le `mouse on` qui
avait été réactivé par erreur.

Contexte :
- Régression : le fix scrollback (commit `3524a07`, déjà présent sur vemao) avait ajouté
  `set -g mouse on` dans `tmuxComfortCmd`. Effet de bord : tmux capture la souris et copie la
  sélection dans son **buffer interne** au lieu du **presse-papier macOS** → impossible de
  sélectionner/copier au CLI en SSH ni dans le Terminal partagé. Les bypass natifs (⌥ Terminal.app/
  iTerm2, ⇧ kitty/WezTerm) ne fonctionnaient pas dans le terminal utilisé.
- Correctif (poussé sur `origin/main` depuis hpcmultimedia) : `Sources/PartageLAN/PartageLAN.swift`
  → `tmuxComfortCmd` force désormais `tmux set -g mouse off`, RETIRE toute ligne `set -g mouse on`
  du `~/.tmux.conf` (auto-réparation des machines déjà configurées) et garde `history-limit 50000`.
  Motifs grep MONO-MOT (`history-limit`, `mouse.on`) car en SSH le shell local mange les quotes
  simples et OpenSSH recolle les args par espaces (un motif multi-mots ferait interpréter `-g`
  comme option de grep).
- hpcmultimedia : déjà rebuild + déployé + copie validée en usage réel.
- vemao : tourne encore l'ANCIEN binaire ; `~/.tmux.conf` contient `set -g mouse on` ; serveur tmux
  courant en `mouse on`. À corriger.
- Rappel signature : le build en session SSH échoue à la signature (`errSecInternalComponent`,
  trousseau inaccessible hors session graphique). **Exécuter en session GRAPHIQUE locale**, ne PAS
  contourner par un repli `codesign -s -` (casserait la stabilité Little Snitch/Gatekeeper).

Tâche (en session GRAPHIQUE locale sur vemao, pas via SSH) :
1. `cd /Users/vemao/Documents/_Programmation/_PartageLAN` ; `git status --short`. Untracked tolérés
   connus : `.gitignore` local et d'éventuels `prompts-remote/*.result.md` non commités. Si un
   fichier SUIVI diverge, s'arrêter et signaler avant de continuer.
2. `git pull --ff-only`. Vérifier que le fix est bien là :
   - `grep -n "mouse off" Sources/PartageLAN/PartageLAN.swift` → doit matcher ;
   - dans `tmuxComfortCmd`, il ne doit PLUS y avoir de `set -g mouse on`.
3. Débloquer la session tmux courante tout de suite : `tmux set -g mouse off 2>/dev/null` (sans
   effet si aucun serveur actif). Le nettoyage du `~/.tmux.conf` sera fait automatiquement par le
   nouveau binaire au prochain lancement de Terminal partagé/SSH ; pour aller vite on peut aussi
   retirer la ligne `set -g mouse on` à la main.
4. Lancer `./PartageLAN.command` directement dans cette session : il refait `git pull` (déjà à
   jour), `setup_signing.sh`, `build_app.sh`, installe dans `/Applications/PartageLAN.app` et
   relance le LaunchAgent `fr.vemao.partagelan`.
5. Vérifier le message « Signé avec « PartageLAN Self-Signed » (signature stable). ». Si repli sur
   signature ad-hoc (avertissement), s'arrêter et signaler, ne pas continuer.
6. Vérifier la relance : `pgrep -fl PartageLAN` → process récent avec bundle `/Applications/PartageLAN.app`.
7. Test fonctionnel : ouvrir « Terminal partagé » depuis l'app ; dans tmux, sélectionner du texte à
   la souris puis ⌘C → doit copier nativement (sans ⌥). Vérifier aussi que remonter dans
   l'historique avec `Ctrl-b [` (puis PgUp/flèches, `q` pour sortir) fonctionne.

Contraintes :
- Pas de commit, pas de push (le fix est déjà poussé depuis hpcmultimedia).
- Ne pas régénérer le certificat de signature s'il est déjà présent ; pas de repli ad-hoc.
- Ne pas piloter d'autre app via AppleScript/System Events ; ne pas piloter la souris réelle.

Livrable : PartageLAN à jour (mouse off), signé « PartageLAN Self-Signed » stable, installé dans
`/Applications`, relancé via le LaunchAgent ; `~/.tmux.conf` de vemao sans `mouse on` ; copie native
vérifiée dans le Terminal partagé.

Compte-rendu : créer `prompts-remote/2026-07-14_06h34_fix-mouse-off-vemao.result.md` (5-10 lignes) :
résultat de `git status --short`, confirmation des greps (`mouse off` présent / `mouse on` absent),
message de signature obtenu, PID de l'instance relancée, résultat du test de copie.
