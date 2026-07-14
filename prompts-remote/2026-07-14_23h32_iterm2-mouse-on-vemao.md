Objectif : Déployer sur CE Mac (vemao, 10.0.0.4) le passage à **iTerm2** : l'app ouvre désormais
les sessions SSH / Terminal partagé dans iTerm2 (au lieu de Terminal.app), et tmux repasse en
`mouse on` + `set-clipboard on`. But : récupérer la **molette** (défilement de l'historique) ET
garder le **copier natif** — impossible ensemble dans Terminal.app, possible dans iTerm2 (bypass ⌥
fonctionnel + OSC 52).

Contexte :
- iTerm2 est déjà installé via MacPorts (`/Applications/MacPorts/iTerm2.app`, bundle id
  `com.googlecode.iterm2`). L'app le lance par bundle id (`open -b com.googlecode.iterm2`), robuste
  quel que soit le chemin.
- Correctif (poussé sur `origin/main` depuis hpcmultimedia) : `Sources/PartageLAN/PartageLAN.swift`
  → les 2 lancements de terminal passent de `open -a Terminal` à `open -b com.googlecode.iterm2` ;
  `tmuxComfortCmd` force désormais `mouse on` + `set-clipboard on`, RETIRE toute ligne
  `set -g mouse off` héritée du fix précédent, et garde `history-limit 50000`. Motifs grep MONO-MOT
  (`history-limit`, `mouse.off`, `mouse.on`, `set-clipboard`) pour survivre au quoting SSH.
- hpcmultimedia : déjà rebuild + déployé (PID 10574), signature « PartageLAN Self-Signed » stable.
- vemao : tourne encore l'ANCIEN binaire (Terminal.app + `mouse off`) ; `~/.tmux.conf` contient
  `set -g mouse off` ; serveur tmux courant en `mouse off`. À corriger.
- Rappel signature : le build en session SSH échoue à la signature (`errSecInternalComponent`,
  trousseau inaccessible hors session graphique). **Exécuter en session GRAPHIQUE locale**, ne PAS
  contourner par un repli `codesign -s -` (casserait la stabilité Little Snitch/Gatekeeper).

Tâche (en session GRAPHIQUE locale sur vemao, pas via SSH) :
1. `cd /Users/vemao/Documents/_Programmation/_PartageLAN` ; `git status --short`. Untracked tolérés
   connus : `.gitignore` local, `.claude-memory/` et d'éventuels `prompts-remote/*.result.md` non
   commités. Si un fichier SUIVI diverge, s'arrêter et signaler avant de continuer.
2. `git pull --ff-only`. Vérifier que le fix est bien là :
   - `grep -n "com.googlecode.iterm2" Sources/PartageLAN/PartageLAN.swift` → doit matcher 2 fois ;
   - `grep -n "mouse on" Sources/PartageLAN/PartageLAN.swift` → doit matcher dans `tmuxComfortCmd` ;
   - il ne doit PLUS y avoir de `open -a Terminal` ni de `tmux set -g mouse off`.
3. Débloquer la session tmux courante tout de suite : `tmux set -g mouse on 2>/dev/null;
   tmux set -g set-clipboard on 2>/dev/null` (sans effet si aucun serveur actif). Le nettoyage du
   `~/.tmux.conf` (retrait du `set -g mouse off`) sera fait automatiquement par le nouveau binaire au
   prochain lancement de Terminal partagé/SSH.
4. Lancer `./PartageLAN.command` directement dans cette session : il refait `git pull` (déjà à
   jour), `setup_signing.sh`, `build_app.sh`, installe dans `/Applications/PartageLAN.app` et relance
   le LaunchAgent `fr.vemao.partagelan`.
5. Vérifier le message « Signé avec « PartageLAN Self-Signed » (signature stable). ». Si repli sur
   signature ad-hoc (avertissement), s'arrêter et signaler, ne pas continuer.
6. Vérifier la relance : `pgrep -fl PartageLAN` → process récent avec bundle `/Applications/PartageLAN.app`.
7. Réglage iTerm2 (une fois) : iTerm2 → Preferences → General → Selection → cocher
   « Applications in terminal may access clipboard » (autorise OSC 52 pour la copie depuis tmux).
8. Test fonctionnel : ouvrir « Terminal partagé » depuis l'app → doit s'ouvrir dans **iTerm2**.
   Dans tmux : (a) la **molette** doit défiler l'historique ; (b) copie = maintenir **⌥ Option**
   pendant la sélection souris puis **⌘C** → doit coller nativement dans le presse-papier macOS.

Contraintes :
- Pas de commit, pas de push (le fix est déjà poussé depuis hpcmultimedia).
- Ne pas régénérer le certificat de signature s'il est déjà présent ; pas de repli ad-hoc.
- Ne pas piloter d'autre app via AppleScript/System Events ; ne pas piloter la souris réelle.

Livrable : PartageLAN à jour (iTerm2 + `mouse on` + `set-clipboard on`), signé « PartageLAN
Self-Signed » stable, installé dans `/Applications`, relancé via le LaunchAgent ; `~/.tmux.conf` de
vemao sans `mouse off` ; ouverture dans iTerm2 + molette + copie ⌥ vérifiées dans le Terminal partagé.

Compte-rendu : créer `prompts-remote/2026-07-14_23h32_iterm2-mouse-on-vemao.result.md` (5-10 lignes) :
résultat de `git status --short`, confirmation des greps (`com.googlecode.iterm2` ×2, `mouse on`
présent / `open -a Terminal` et `mouse off` absents), message de signature obtenu, PID de l'instance
relancée, résultat des tests (ouverture iTerm2, molette, copie ⌥).
