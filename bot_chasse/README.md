# Bot Discord « Chasse »

Dans un salon dédié, colle ton armée : le bot répond avec le tableau du risque selon la taille de chasse.

```
1 208 JSN + 99 SN, Armes 1, Bouclier 2, TDC 2 770
```

Ajoute `réplique 30` (ou `réplique 50`) pour compter le risque sur la réplique 30 % au lieu de 10 % : mêmes lignes 🛡 📈 ⭐ 🔥, mais pour des chasses plus grosses. Écritures acceptées : replique, réplique, repliques, répliques. Sans ce mot, le bot compte sur 10 %.

Ajoute `perte 100` pour avoir seulement la plus grosse chasse dont le **pire cas** reste ≤ 100 pertes : une ligne (Chasse, Pertes moy., cm²/perte, Pire cas), puis « 📊 Chances selon les pertes » : 4 tranches égales de 0 à la limite (`BUCKETS`), avec le % des chasses dans chacune (total 100 %), sans réplique. Si le pire cas touche d'autres unités que les JSN, une ligne en dessous donne le détail exact du pire combat (« Pire cas : 80 JSN + 20 SN »). Une tranche presque vide affiche « < 0,1 % » (0 % = jamais). Une limite égale ou plus grande que l'armée est ramenée à l'armée moins 1 : une chasse perdue n'est jamais proposée. Écritures acceptées : perte 100, pertes 100, perte max 100, pertes: 100, 100 pertes.

Il comprend aussi le format du jeu (« 1 208 Jeunes Soldates Naines, 99 Soldates Naines… »). Unités : toutes (JSN, SN, NE, JS, S, C, CE, A, AE, SE, Tk, TkE, Tu, TuE), noms longs ou abréviations ; S, C et A seuls en majuscule. Le TDC est obligatoire.

**Fiche du joueur** : ce qui manque dans le message (armée, Armes, Bouclier) est pris dans sa fiche (salon profil). Avec une fiche complète, `TDC 2 770` suffit. Le tableau commence alors par « 📋 Pris dans ta fiche : armée du 19/10/2026 14:02, Armes, Bouclier ». Sans fiche, Armes et Bouclier absents = niveau 0.
- Ce qui est écrit dans le message passe avant la fiche, et **remplace** la fiche : la dernière armée donnée fait foi (aussi une armée seule envoyée pour le niveau d'Armes). Pareil pour Armes et Bouclier.
- Le TDC n'est jamais enregistré.

Armée seule (sans Armes, Bouclier, TDC, perte ni réplique) : le bot calcule le niveau d'Armes rentable au lieu du tableau. Il demande l'unité pondue (menu, bouton, ou son nom envoyé dans le salon), puis remplace la question par le résultat.

`/niveau-armes` (commande slash, réponse visible de toi seul) : niveau d'Armes rentable.
1. Un formulaire s'ouvre : colle ton armée (`600 Jeunes Soldates Naines, 236 SN, 700 JS`). Toutes les unités sont acceptées, noms complets (singulier ou pluriel) ou abréviations, séparées par des virgules, `;`, `+` ou des lignes. Une unité inconnue est refusée (sinon la FdF serait trop basse).
2. Choisis l'unité que tu ponds dans le menu (JSN, JS, Artilleuses, Tanks, Tueuses d'élite), ou clique « Saisir le nom de l'unité » pour une autre.
3. Le bot affiche le niveau max rentable en titre, puis en gras : FdF hors bonus (HB) actuelle, FdF HB du niveau suivant, ce qui manque ; et l'unité pondue.

Modèle (onglet « calcul manuel » du classeur BDD, valeurs intégrées dans `niveau_armes.py`) : passer à Armes n coûte C(n) = 80 × 2^(n−1) ouvrières de 60 s. Le niveau est rentable si 10 % de la FdF HB ≥ la FdF des unités pondues pendant ce temps à Armes n−1, soit HB ≥ S(n) = plafond(C(n) × 60 / ponte × attaque × (n + 9)). Ponte continue : seul S(n) est arrondi. Une question expire après 5 minutes ; relancer la commande remplace l'ancienne.

## Rentabilité de l'Étable à pucerons
Dans un salon chasse, écris seulement `ov 15000` (aussi `Ouv 15000`, `ov: 15 000`, `ouvrières 15000`, `15000 ov`). Une phrase (« j'ai 15000 ov ») ne déclenche rien. Ou commande `/renta puceron ouvrieres:15000` partout.
- Mets tes ouvrières **disponibles** (celles qui n'exploitent pas le TDC).
- Le bot donne le dernier passage rentable (n → n+1), son coût en ov et le gain de capacité de convoi (tableau Avant / Après).
- Bouton « Calculer avec mon niveau actuel » : niveau max rentable depuis ton niveau (0 = pas d'étable), coûts déduits au fur et à mesure.
- Bouton « Voir les valeurs exactes » : chiffres complets, visibles de toi seul.
- Boutons réservés à l'auteur, 5 minutes. Un nouvel effectif remplace la question en attente.
- Modèle : capacité 10 + 0,5 × niveau par ouvrière. Coût en ov modélisé, non vérifié (niveau 1 = Communication 1 à 3 = 560 ov, puis 320 × 2^n) ; le bois n'est pas compté. Détails : `connaissances/mecaniques.md`.

## Salon profil (pseudo en jeu, ov, Champignonnière, Étable à pucerons, armée, Armes, Bouclier)
Dans le salon `1559888062430052474`, chaque joueur écrit par exemple `pseudo Missyl ov 1 234 567 champi 12 puceron 8`, ou colle son armée : `1 425 Jeunes Soldates Naines, 359 Soldates Naines, 100 Naines d’Elites, armes 8, bouclier 7` (mêmes écritures que le salon chasse). Le bot met à jour **sa** fiche et répond « ✅ Enregistré » sans notification.
- La fiche est dans une base SQLite (`fiches.db`, à côté du bot), qui fait foi. Chaque enregistrement est recopié dans **sa** ligne du Google Sheet (une ligne par compte Discord : Nom Discord, ID In Game, ID Discord, Ouvrières, Champignonnière, Étable à pucerons, Mis à jour, Armes, Bouclier, Armée). Une case modifiée à la main dans le sheet n'est pas relue : elle est écrasée au prochain enregistrement du joueur.
- Base vide au démarrage (premier lancement, machine de secours) : elle est remplie depuis le sheet.
- Si la copie dans le sheet échoue, la fiche est quand même enregistrée et le bot le signale.
- Pseudo en jeu : `pseudo X`, `ig X`, `in game X`, `id in game X`, `id ig X` (un mot : lettres, chiffres, `_`, `-`, `.` ; majuscules gardées). Sans mot-clé, un premier mot qui n'est ni un nombre ni un mot-clé est pris comme pseudo s'il est suivi d'au moins une valeur (`DogGyneco ov 63981 champi 12`).
- La ligne du joueur est retrouvée par son **ID Discord** (un changement de pseudo Discord ne crée pas de doublon) et chaque colonne par son **titre** : on peut déplacer des colonnes ou en ajouter à la main, le bot n'écrit que dans les siennes. Une colonne du bot absente est recréée en fin de tableau. Ne pas renommer les titres des colonnes du bot.
- Écritures acceptées : ov, ovs, ouv, ouvrière(s), ouvrier(s) ; champ, champi(s), champignon(s), champignonnière ; puc, puceron(s), étable(s), étable à pucerons. Majuscules et accents indifférents. `:`, `=`, `niv`, `lvl` acceptés entre le mot et le nombre.
- Nombres : `1234567`, `1 234 567`, `1.234.567`. Le nombre peut aussi être avant le mot si le message commence par un nombre (`12 champi 8 puceron`).
- On peut n'en donner qu'une partie (`champi 13`) : les autres valeurs restent.
- `.env` : `GSHEET_KEY=chemin/vers/cle.json` (compte de service, **Éditeur** sur le sheet) et `PROFIL_SHEET_ID=…`. Sans eux, les fiches sont seulement dans la base. `FICHES_DB=…` pour mettre la base ailleurs.

## `/niveau-joueur` : export CSV des fiches OUAF
Commande slash, réponse visible de toi seul : un fichier `niveau_joueur.csv` (et son texte, copiable sur mobile).
- Colonnes : `player_id,pseudo,etable_puceron,champi,ouvriere`, triées par pseudo.
- Lignes : les membres de l'alliance (`ALLIANCE` dans `.env`, OUAF par défaut) d'après l'API des exports publics du
  jeu, qui donne le `player_id`, complétés par les fiches de la base (pseudo comparé sans la casse). Valeur absente = 0.
- Une fiche dont le pseudo n'est pas dans l'API garde un `player_id` vide. Si l'API est injoignable,
  l'export part des fiches seules et le bot le signale.

## Fichiers
- `risque.py` : lecture du texte et calcul (moteur `hunt_mc.py`, copié depuis `tools/`). Essai : `python risque.py "948 JSN, Armes 2, Bouclier 2, TDC 2 148"`.
- `niveau_armes.py` : commande `/niveau-armes` (calcul + formulaire, menu, 4 emojis intégrés).
- `renta_puceron.py` : `/renta puceron` et message `ov 15000` (calcul, boutons, fenêtre du niveau actuel).
- `profil.py` : salon profil (lecture du message + copie dans le Google Sheet) et export CSV de `/niveau-joueur`.
- `fiches.py` : base SQLite des fiches (fait foi ; remplie depuis le sheet si vide).
- `bot.py` : le bot (lit les salons de `CHANNEL_ID`, séparés par des virgules : un salon par serveur Discord). Dans les salons de `SILENT_CHANNEL_IDS`, il répond sans notification.
- `.env` (sur le Pi seulement, secret) : `DISCORD_TOKEN=…` et `CHANNEL_ID=…`.
- `bot-chasse.service` : service systemd (redémarre tout seul).

## Installation (déjà faite sur le Pi, dans `~/MyProjects/bot_chasse`)
1. Créer le bot sur https://discord.com/developers/applications : activer **Message Content Intent**, puis l'inviter avec les permissions View Channels, Send Messages, Read Message History.
2. Sur le Pi : `nano ~/MyProjects/bot_chasse/.env` et remplir le token et l'ID du salon.
3. `sudo systemctl start bot-chasse` ; journal : `journalctl -u bot-chasse -f`.

## Mettre à jour
Depuis le PC, dans `bot_chasse/` :
```
scp bot.py risque.py niveau_armes.py profil.py renta_puceron.py ../tools/hunt_mc.py raspberrypi:MyProjects/bot_chasse/
ssh raspberrypi sudo systemctl restart bot-chasse
```

## Tests
`python -m pytest tests/test_bot_chasse.py` (depuis la racine du projet).

## Choix
- Lecture d'un salon (pas de commande `/`) : on colle et c'est tout. Il faut l'intent « Message Content ».
- Lignes du tableau (4 au plus, fusionnées si deux tombent sur la même taille) : 🛡 min. pertes = la plus grosse chasse à 1 % de risque ; 📈 meilleur cm²/perte parmi les chasses à 1, 2, 5, 7,5, 10, 15 et 20 % de risque ; ⭐ opti = la plus grosse chasse qui garde au moins 85 % du meilleur cm²/perte ; 🔥 flemme = 80 % (`STARS`). 5 000 tirages par taille.
- cm²/perte compte toutes les répliques (10, 30, 50 ou 100 % selon la force face aux prédateurs) : pas besoin de choisir un seuil de réplique.
- Sous les paramètres : FDF = attaque totale de l'armée × (1 + Armes/10), comme le moteur.
- Mêmes tirages pour toutes les tailles et tous les TDC (préparés une fois par meute) + cache : les résultats ne sautent pas au hasard.
- ⭐/🔥 : le cm²/perte remonte par endroits (paliers de réplique), donc on balaie les tailles au lieu d'une recherche dichotomique (qui s'arrêtait trop tôt).
- Calcul réparti sur tous les cœurs (4 sur le Pi) ; s'il échoue, il repasse sur un seul cœur.
