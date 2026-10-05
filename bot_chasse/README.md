# Bot Discord « Chasse »

Dans un salon dédié, colle ton armée : le bot répond avec le tableau du risque selon la taille de chasse.

```
1 208 JSN + 99 SN, Armes 1, Bouclier 2, TDC 2 770
```

Ajoute `réplique 30` (ou `réplique 50`) pour compter le risque sur la réplique 30 % au lieu de 10 % : mêmes lignes 🛡 📈 ⭐ 🔥 et 📅, mais pour des chasses plus grosses. Écritures acceptées : replique, réplique, repliques, répliques. Sans ce mot, le bot compte sur 10 %.

Ajoute `perte 100` pour avoir seulement la plus grosse chasse dont le **pire cas** reste ≤ 100 pertes : une ligne (Chasse, Pertes moy., cm²/perte, Pire cas), sans réplique ni prochaines chasses. Écritures acceptées : perte 100, pertes 100, perte max 100, pertes: 100, 100 pertes.

Il comprend aussi le format du jeu (« 1 208 Jeunes Soldates Naines, 99 Soldates Naines… »). Unités : toutes (JSN, SN, NE, JS, S, C, CE, A, AE, SE, Tk, TkE, Tu, TuE), noms longs ou abréviations ; S, C et A seuls en majuscule. Armes et Bouclier absents = niveau 0. Le TDC est obligatoire.

## Fichiers
- `risque.py` : lecture du texte et calcul (moteur `hunt_mc.py`, copié depuis `tools/`). Essai : `python risque.py "948 JSN, Armes 2, Bouclier 2, TDC 2 148"`.
- `bot.py` : le bot (lit les salons de `CHANNEL_ID`, séparés par des virgules : un salon par serveur Discord).
- `.env` (sur le Pi seulement, secret) : `DISCORD_TOKEN=…` et `CHANNEL_ID=…`.
- `bot-chasse.service` : service systemd (redémarre tout seul).

## Installation (déjà faite sur le Pi, dans `~/MyProjects/bot_chasse`)
1. Créer le bot sur https://discord.com/developers/applications : activer **Message Content Intent**, puis l'inviter avec les permissions View Channels, Send Messages, Read Message History.
2. Sur le Pi : `nano ~/MyProjects/bot_chasse/.env` et remplir le token et l'ID du salon.
3. `sudo systemctl start bot-chasse` ; journal : `journalctl -u bot-chasse -f`.

## Mettre à jour
Depuis le PC, dans `bot_chasse/` :
```
scp bot.py risque.py ../tools/hunt_mc.py raspberrypi:MyProjects/bot_chasse/
ssh raspberrypi sudo systemctl restart bot-chasse
```

## Tests
`python -m pytest tests/test_bot_chasse.py` (depuis la racine du projet).

## Choix
- Lecture d'un salon (pas de commande `/`) : on colle et c'est tout. Il faut l'intent « Message Content ».
- Lignes du tableau (4 au plus, fusionnées si deux tombent sur la même taille) : 🛡 min. pertes = la plus grosse chasse à 1 % de risque ; 📈 meilleur cm²/perte parmi les chasses à 1, 2, 5, 7,5, 10, 15 et 20 % de risque ; ⭐ opti = la plus grosse chasse qui garde au moins 85 % du meilleur cm²/perte ; 🔥 flemme = 80 % (`STARS`). 5 000 tirages par taille.
- cm²/perte compte toutes les répliques (10, 30, 50 ou 100 % selon la force face aux prédateurs) : pas besoin de choisir un seuil de réplique.
- 📅 5 prochaines chasses ⭐ (`NEXT_HUNTS`), lancées l'une après l'autre : le TDC monte de la taille chassée et l'armée perd le **pire cas** (choix prudent : une grosse réplique sur la 1re chasse pèse sur les suivantes). Les JSN meurent d'abord.
- Mêmes tirages pour toutes les tailles et tous les TDC (préparés une fois par meute) + cache : les résultats ne sautent pas au hasard.
- ⭐/🔥 : le cm²/perte remonte par endroits (paliers de réplique), donc on balaie les tailles au lieu d'une recherche dichotomique (qui s'arrêtait trop tôt).
- Calcul réparti sur tous les cœurs (4 sur le Pi) ; s'il échoue, il repasse sur un seul cœur.
- Réponse en 2 temps : le tableau d'abord (~1-3 s sur le Pi), puis le message est complété avec les prochaines chasses (~6-11 s de plus).
