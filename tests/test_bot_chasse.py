import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bot_chasse"))
import risque  # noqa: E402

import pytest  # noqa: E402


def test_lecture_format_court():
    assert risque.parse("1 208 JSN + 99 SN, Armes 1, Bouclier 2, TDC 2 770") == ({"jsn": 1208, "sn": 99}, 1, 2, 2770)


def test_lecture_format_rc_et_espaces_insecables():
    text = "Troupes en attaque : 1 208 Jeunes Soldates Naines, 99 Soldates Naines, 40 Jeunes Soldates. " \
           "Armes 2 Bouclier Thoracique 1, 2 148 cm²"
    assert risque.parse(text) == ({"jsn": 1208, "sn": 99, "js": 40}, 2, 1, 2148)


def test_erreurs_claires():
    with pytest.raises(risque.ParseError, match="TDC"):
        risque.parse("1 208 JSN, Armes 1")
    assert risque.answer("bonjour").startswith("❌ Aucune unité")


def test_risque_comme_le_calcul_du_04_10():
    """70 cm² à 2 770 TDC (1 208 JSN + 99 SN, Armes 1, Bouclier 2) : ~7,5 % ; 60 cm² : ~1 %."""
    army = {"jsn": 1208, "sn": 99}
    assert 5 < risque.stats(army, 2770, 70, 1, 2, 3000)[0] < 10
    assert risque.stats(army, 2770, 60, 1, 2, 3000)[0] < 2


def test_tableau_pret_pour_discord():
    """Seulement les lignes utiles (🛡 📈 ⭐ 🔥), puis les 5 prochaines chasses ⭐."""
    out = risque.answer("1 208 JSN + 99 SN, Armes 1, Bouclier 2, TDC 2 770")
    lines = out.splitlines()
    assert lines[0] == lines[-1] == "```"
    assert lines[2] == "   (1 208 JSN + 99 SN, Armes 1, Bouclier 2, TDC 2 770)"
    rows = lines[6:lines.index("🛡 min. pertes  📈 meilleur cm²/perte")]
    sizes = [int(r.split()[0]) for r in rows]
    assert sizes == sorted(sizes) and 55 <= sizes[0] <= 64 and 2 <= len(rows) <= 4
    assert all(len(r.split("|")) == 5 for r in rows)
    roles = "".join(r.split()[-1] for r in rows)
    assert sorted(roles) == sorted("🛡📈⭐🔥") and "🛡" in rows[0]
    plan = lines[lines.index("📅 5 prochaines chasses ⭐ (pire cas retiré à chaque fois)") + 3:-2]
    assert [r.split()[0] for r in plan] == ["1", "2", "3", "4", "5"]
    assert plan[0].split("|")[2].split()[0] == next(r for r in rows if "⭐" in r).split()[0]
    assert lines[-2].startswith("Après : TDC ")


def test_reponse_rapide_puis_prochaines_chasses():
    fast = risque.answer("1 208 JSN + 99 SN, Armes 1, Bouclier 2, TDC 2 770", plan=False)
    full = risque.answer("1 208 JSN + 99 SN, Armes 1, Bouclier 2, TDC 2 770")
    assert risque.WAIT_PLAN in fast and "📅 5 prochaines" not in fast
    assert full.startswith(fast.split("\n\n" + risque.WAIT_PLAN)[0])    # même tableau, complété


def test_prochaines_chasses_pire_cas_retire():
    """Le TDC monte de la taille chassée, l'armée perd le pire cas (JSN d'abord), la ⭐ ne saute pas au hasard."""
    army = {"jsn": 948}
    plan, after, tdc = risque.next_hunts(army, 2, 2, 2148)
    assert len(plan) == 5 and plan[0][0] == 2148
    for (t1, s1, w1), (t2, s2, _) in zip(plan, plan[1:]):
        assert t2 == t1 + s1 and abs(s2 - s1) <= 6
    assert tdc == plan[-1][0] + plan[-1][1] and after == {"jsn": 948 - sum(w for _, _, w in plan)}


def test_pertes_les_plus_faibles_d_abord():
    assert risque.lose({"jsn": 10, "sn": 5}, 12) == {"sn": 3}
    assert risque.lose({"jsn": 10}, 30) == {}


def test_etoile_sur_la_plus_grosse_chasse_rentable():
    """1 027 JSN + 104 SN, Armes 2, Bouclier 2, TDC 2 826 : ⭐ vers 70-75 cm², 🔥 au moins aussi gros."""
    rows = risque.key_rows({"jsn": 1027, "sn": 104}, 2, 2, 2826)
    star = next(r[0] for r in rows if "⭐" in r[5])
    fire = next(r[0] for r in rows if "🔥" in r[5])
    assert 66 <= star <= 78 <= fire + 4 and fire >= star


def test_meilleur_ratio_vraiment_le_meilleur():
    """📈 = vrai sommet du cm²/perte (~95 cm² ici), pas la meilleure taille repère : le bouclier ne le fait pas reculer."""
    army = {"jsn": 944, "sn": 184, "ne": 1, "js": 219, "s": 2}
    best = {}
    for bouclier in (3, 4):
        rows = risque.key_rows(army, 3, bouclier, 4360)
        size, ratio = next((r[0], r[4]) for r in rows if "📈" in r[5])
        scan = [s / risque.stats(army, 4360, s, 3, bouclier, 5000)[1] for s in range(60, 141, 5)]
        assert ratio >= max(scan) - 1e-9
        best[bouclier] = size
    assert best[4] >= best[3] - 2 and 90 <= best[3] <= 100


@pytest.mark.parametrize("text", [
    "1 208 JSN + 99 SN, Armes 1, Bouclier 2, TDC 2 770",
    "TDC 2770 / armes 1 / bouclier 2 / 1208 jsn 99 sn",
    "bouclier: 2 arme: 1 tdc: 2 770 1 208 JSN, 99 SN",
    "1208 JSNs + 99 SNs, ARMES niv. 1, Bouclier Thoracique niveau 2, 2 770 cm²",
    "JSN 1208, SN 99, Armes=1, Bouc 2, TDC=2770",
    "1 armes, 2 bouclier, 2770 tdc, 1208 jeune soldate naine, 99 soldates naines",
    "1.208 JSN\n99 SN\nArmes 1\nBouclier 2\nTerrain de chasse 2 770",
    "1 208 Jeunes Soldates Naines 99 Soldates Naines, armes1 , bouclier2 .TDC2770",
])
def test_lecture_souple(text):
    assert risque.parse(text) == ({"jsn": 1208, "sn": 99}, 1, 2, 2770)


def test_toutes_les_unites():
    text = ("906 Jeunes Soldates Naines, 186 Soldates Naines, 6 Naines d’Elites, 98 Jeunes Soldates, 10 Soldates, "
            "5 Soldates d'élite, 3 Tanks, 2 Tank d'élite, 4 Tueuses, 1 Tueuse d'élite, 7 Artilleuses, 8 Artilleuses d'élite, "
            "2 Concierges, 1 Concierge d'élite, armes 2, bouclier 2, tdc 3944")
    army = risque.parse(text)[0]
    assert army == {"jsn": 906, "sn": 186, "ne": 6, "js": 98, "s": 10, "c": 2, "ce": 1, "a": 7, "ae": 8, "se": 5,
                    "tk": 3, "tke": 2, "tu": 4, "tue": 1}
    assert risque.parse("50 S, 20 A, 3 Tk, 10 NE, armes 1, bouclier 1, tdc 2000")[0] == {"ne": 10, "s": 50, "a": 20,
                                                                                         "tk": 3}
    assert risque.parse("100 jsn, tdc 2000, armes 1")[0] == {"jsn": 100}       # « a » minuscule : pas une unité


def test_ordre_de_mort_jsn_d_abord():
    import hunt_mc
    prey = [0] * len(hunt_mc.PREY)
    prey[0] = 10                                                         # 10 petites araignées
    assert set(hunt_mc.fight_losses({"jsn": 100, "ne": 50, "tk": 5}, prey)) == {"jsn", "ne", "tk"}
    assert hunt_mc.fight_losses({"jsn": 100, "ne": 50, "tk": 5}, prey)["tk"] == 0


def test_easter_egg_enorme_teub():
    for text in ("énorme teub", "Une ÉNORME  teub !", "enorme teub"):
        assert risque.answer(text) == risque.ENORME_TEUB
    assert risque.answer("teub").startswith("❌")


def test_easter_egg_envoye_en_silencieux():
    src = (Path(__file__).resolve().parent.parent / "bot_chasse" / "bot.py").read_text(encoding="utf-8")
    assert "silent = reply == risque.ENORME_TEUB" in src and "silent=silent" in src
    assert "SILENT_CHANNEL_IDS = {1556337362211053741}" in src and "in SILENT_CHANNEL_IDS" in src


@pytest.mark.parametrize("word", ["replique", "réplique", "repliques", "répliques", "Réplique", "RÉPLIQUES"])
def test_replique_toutes_les_ecritures(word):
    for suffix, rep in ((f" {word} 30", 30), (f", {word}: 50 %", 50), (f" {word}=10", 10)):
        assert risque.replique("1 208 JSN, TDC 2 770" + suffix)[0] == rep
    assert risque.parse(risque.replique(f"1 208 JSN + 99 SN, {word} 30, Armes 1, Bouclier 2, TDC 2 770")[1]) == \
        ({"jsn": 1208, "sn": 99}, 1, 2, 2770)


def test_replique_par_defaut_10_et_valeur_impossible():
    assert risque.replique("1 208 JSN, TDC 2 770") == (10, "1 208 JSN, TDC 2 770")
    assert risque.answer("1 208 JSN, TDC 2 770, réplique 40").startswith("❌ Réplique 40 % impossible")


def test_tableau_replique_30():
    """Même modèle, colonne « Réplique > 30 % » et chasses plus grosses qu'en 10 %."""
    text = "1 050 JSN + 154 SN + 218 JS, Armes 1, Bouclier 1, TDC 3 770"
    normal, rep30 = risque.answer(text, plan=False), risque.answer(text + ", réplique 30", plan=False)
    assert "Réplique > 10 %" in normal and "Chasses conseillées\n" in normal
    assert "Réplique > 30 %" in rep30 and "🎯 Chasses conseillées (réplique 30 %)" in rep30
    first = lambda out: int(next(l for l in out.splitlines() if "🛡" in l and "|" in l).split()[0])
    assert first(rep30) > first(normal) + 30


def test_vrai_meilleur_ratio_avec_replique_30():
    """📈 ne dépend pas de la réplique comptée : même taille qu'en 10 %. ⭐ reste propre au tableau 30 %."""
    army = {"jsn": 1208, "sn": 99}
    normal, rep30 = risque.key_rows(army, 1, 2, 2770), risque.key_rows(army, 1, 2, 2770, rep=30)
    best = lambda rows: next(r[0] for r in rows if "📈" in r[5])
    star = lambda rows: next(r[0] for r in rows if "⭐" in r[5])
    assert best(rep30) == best(normal) and star(rep30) > star(normal) + 15
    assert "🛡" in next(r for r in rep30 if r[0] > best(normal))[5]


@pytest.mark.parametrize("suffix", [", perte 100", ", pertes 100", ", Perte max 100", ", pertes: 100", ", 100 pertes"])
def test_perte_toutes_les_ecritures(suffix):
    cap, rest = risque.perte("1 208 JSN + 99 SN, Armes 1, Bouclier 2, TDC 2 770" + suffix)
    assert cap == 100 and risque.parse(rest) == ({"jsn": 1208, "sn": 99}, 1, 2, 2770)
    assert risque.perte("1 208 JSN, TDC 2 770") == (None, "1 208 JSN, TDC 2 770")


def test_tableau_perte_max_une_ligne():
    """Plus grosse chasse au pire cas ≤ 100 : une ligne, sans colonne réplique ni prochaines chasses."""
    out = risque.answer("1 208 JSN + 99 SN, Armes 1, Bouclier 2, TDC 2 770, perte 100")
    lines = out.splitlines()
    assert lines[0] == lines[-1] == "```" and lines[1] == "🎯 Chasse pour 100 pertes max"
    assert "Réplique" not in out and "📅" not in out and "⭐" not in out
    size, mean, _, worst = [c.split()[0] for c in lines[-8].split("|")]
    assert 190 <= int(size) <= 230 and 40 < float(mean.replace(",", ".")) < 80 and int(worst) <= 100
    assert lines[-6] == "📊 Chances selon les pertes :"
    assert [l.split(" pertes")[0].strip() for l in lines[-5:-1]] == ["0 à 25", "26 à 50", "51 à 75", "76 à 100"]
    assert round(sum(float(l.split(": ")[1].split()[0].replace(",", ".")) for l in lines[-5:-1]), 1) == 100
    assert "Pire cas :" not in out                                                 # assez de JSN : pas de détail
    army = {"jsn": 1208, "sn": 99}
    assert risque.stats(army, 2770, int(size) + 1, 1, 2, 5000)[2] > 100          # 1 cm² de plus : trop de pertes


def test_perte_impossible():
    assert "Aucune chasse possible" in risque.answer("10 JSN, TDC 50 000, perte 0")


def test_detail_des_pertes_du_vrai_pire_combat():
    """Pire cas en unités : le détail exact du pire combat, sa somme = le pire cas, même calcul sur 1 ou 4 cœurs."""
    army = {"jsn": 80, "sn": 1200}
    _, _, worst, _, units = risque.stats(army, 2770, 273, 1, 2, 5000)
    assert sum(units.values()) == worst and units["jsn"] == 80 and units["sn"] > 0
    assert risque._chunk(army, 2770, 273, 1, 2, 1, 0, 5000)[2] == units
    out = risque.answer("80 JSN + 1 200 SN, Armes 1, Bouclier 2, TDC 2 770, perte 100").splitlines()
    assert out[-9].split("|")[-1].strip().isdigit() and out[-8].startswith("Pire cas : 80 JSN + ")


def test_perte_jamais_une_chasse_perdue():
    """Limite au-delà de l'armée : plafonnée à l'armée moins 1, la chasse reste gagnée."""
    out = risque.answer("1 208 JSN + 99 SN, Armes 1, Bouclier 2, TDC 2 770, perte 100000").splitlines()
    assert out[1] == "🎯 Chasse pour 1 306 pertes max"
    row = next(l for l in out if "cm²  |" in l or " cm² |" in l)
    assert int(row.split()[0]) < 1000 and int(row.split("|")[-1]) <= 1306


def test_tranches_de_pertes_font_100():
    from collections import Counter
    losses = Counter({0: 1, 10: 1, 30: 1, 99: 3})
    assert risque.buckets(losses, 100) == [(0, 25, 33.3, 2), (26, 50, 16.7, 1), (51, 75, 0, 0), (76, 100, 50, 3)]
    assert sum(p for _, _, p, _ in risque.buckets(Counter(range(7)), 100)) == 100
    assert risque.buckets(Counter({0: 2, 3: 1}), 2) == [(0, 0, 66.7, 2), (1, 1, 0, 0), (2, 3, 33.3, 1)]   # petite limite


def test_tranche_minuscule_pas_zero():
    """1 chasse sur 5 000 : « < 0,1 % », pas « 0 % » ; une tranche vide reste à 0 %."""
    from collections import Counter
    rows = risque.buckets(Counter({0: 4999, 99: 1}), 100)
    assert [(p, c) for _, _, p, c in rows] == [(100, 4999), (0, 0), (0, 0), (0, 1)]


def test_message_pertes_collees_au_tdc():
    out = risque.answer("1 208 JSN, Armes 1, TDC 2 770 100 pertes")
    assert out.startswith("❌ TDC introuvable") and "mets une virgule avant" in out
    assert "virgule" not in risque.answer("1 208 JSN, Armes 1")


def test_perte_pire_cas_irregulier():
    """Le pire cas redescend parfois (194 cm² : 102, 196 cm² : 101) : 101 pertes doit trouver 197 cm², pas 193."""
    army = {"jsn": 1087, "sn": 250, "ne": 28}
    size = risque.max_loss_size(army, 1, 2, 4351, 101)
    assert size == max(s for s in range(150, 260) if risque.stats(army, 4351, s, 1, 2, 5000)[2] <= 101)


# --- /niveau-armes : niveau d'Armes rentable (onglet « calcul manuel ») ---
import asyncio  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import niveau_armes as na  # noqa: E402

ARMY_REF = "600 Jeunes Soldates Naines, 236 Soldates Naines, 20 Naines d’Elites, 700 Jeunes Soldates, 43 Soldates."


def test_armes_exemple_de_reference():
    assert na.analyse_armes(ARMY_REF, "Jeunes Soldates") == {
        "fdf_hb": 10765, "niveau_max": 4, "niveau_suivant": 5, "cible_hb": 14530, "unite_produite": "Jeune Soldate"}


@pytest.mark.parametrize("produced, level, nxt, target", [
    ("Jeunes Soldates Naines", 5, 6, 23040),
    ("Jeunes Soldates", 4, 5, 14530),
    ("Tanks", 3, 4, 14762),
    ("Tueuses d’élite", 4, 5, 21583),
])
def test_armes_quatre_productions_du_menu(produced, level, nxt, target):
    r = na.analyse_armes(ARMY_REF, produced)
    assert (r["fdf_hb"], r["niveau_max"], r["niveau_suivant"], r["cible_hb"]) == (10765, level, nxt, target)


def test_armes_tableau_de_controle_des_seuils():
    table = {"Jeune Soldate Naine": [480, 1056, 2304, 4992, 10752, 23040],
             "Jeune Soldate": [649, 1428, 3114, 6746, 14530, 31136],
             "Tank": [1420, 3123, 6813, 14762, 31794, 68130],
             "Tueuse d’élite": [964, 2120, 4625, 10021, 21583, 46249]}
    for name, targets in table.items():
        unit = na.DATA.unit(name)
        assert [na.threshold(na.DATA, unit, n, c) for n, c in na.DATA.costs[:6]] == targets
    assert na.DATA.costs[-1] == (50, 45035996273704960)


def test_armes_egalite_au_seuil_et_juste_en_dessous():
    assert na.analyse_armes("674 JS + 2 JSN", "JS")["niveau_max"] == 4      # 6 746 HB = S(4) en JS : rentable
    assert na.analyse_armes("674 JS + 1 SN", "JS")["niveau_max"] == 3       # 6 745 HB : un de moins
    assert na.analyse_armes("160 JSN", "JSN")["niveau_max"] == 1            # 480 HB = S(1) en JSN
    assert na.analyse_armes("159 JSN + 1 OV", "JSN") == {
        "fdf_hb": 477, "niveau_max": 0, "niveau_suivant": 1, "cible_hb": 480, "unite_produite": "Jeune Soldate Naine"}


def test_armes_tous_niveaux_rentables():
    r = na.analyse_armes("10" + "0" * 20 + " Tk", "JSN")
    assert r["niveau_max"] == 50 and r["niveau_suivant"] is None and r["cible_hb"] is None


def test_armes_singulier_pluriel_abreviations_et_espaces():
    army = na.parse_army("1 Jeune Soldate Naine; 2 000 jeunes soldates naines\n3 000 JSN + 1 Tank d'élite, 2 TKE")
    assert army == {"Jeune Soldate Naine": 5001, "Tank d’élite": 3}
    assert na.parse_army("1 JS, 1 JSN, 1 S, 1 SE, 1 Tu, 1 TuE") == {
        "Jeune Soldate": 1, "Jeune Soldate Naine": 1, "Soldate": 1, "Soldate d’élite": 1, "Tueuse": 1, "Tueuse d’élite": 1}
    assert na.DATA.unit("Tueuse d'élite").name == "Tueuse d’élite"
    assert na.DATA.unit("TANKS").name == "Tank"


@pytest.mark.parametrize("text", ["600 JSN, 12 Fourmis volantes", "600 JSN, beaucoup de SN", "", "0 JSN",
                                  "-5 JSN", "5.5 JSN", "5,5 JSN"])
def test_armes_saisies_rejetees(text):
    with pytest.raises(na.ArmesError):
        na.parse_army(text)


def test_armes_ouvriere_refusee_comme_production():
    with pytest.raises(na.ArmesError):
        na.analyse_armes("600 JSN", "Ouvrière")


def _interaction(user_id):
    sent = []
    response = SimpleNamespace(send_message=lambda *a, **k: _record(sent, a, k))
    return SimpleNamespace(user=SimpleNamespace(id=user_id), response=response), sent


async def _record(sent, args, kwargs):
    sent.append((args, kwargs))


class _Message:
    def __init__(self):
        self.edits = []

    async def edit(self, **kwargs):
        self.edits.append(kwargs)


def test_armes_sessions_par_joueur_et_expiration():
    async def scenario():
        sessions = na.Sessions()
        army = na.parse_army(ARMY_REF)
        a1, b = na.UnitView(1, army, sessions, {}), na.UnitView(2, army, sessions, {})
        a1.message, b.message = _Message(), _Message()
        await sessions.replace(1, a1)
        await sessions.replace(2, b)
        # un autre joueur ne peut pas utiliser la question
        inter, sent = _interaction(2)
        assert not await a1.interaction_check(inter) and sent and sent[0][1]["ephemeral"]
        # une nouvelle armée du joueur 1 clôt son ancienne question, pas celle du joueur 2
        a2 = na.UnitView(1, army, sessions, {})
        await sessions.replace(1, a2)
        assert a1.finished and a1.message.edits[-1]["view"] is None
        assert not b.finished and sessions.pending == {1: a2, 2: b}
        # expiration après 5 min, même si la View n'a pas encore déclenché son timeout
        a2.expires = 0
        inter, sent = _interaction(1)
        await a2.finish(inter, "JS")
        assert "expirée" in sent[0][0][0]
        await b.on_timeout()
        assert b.finished and "expirée" in b.message.edits[-1]["content"] and 2 not in sessions.pending

    assert na.TIMEOUT == 300
    asyncio.run(scenario())


def test_armes_bot_garde_ses_autres_evenements():
    import os
    os.environ.setdefault("CHANNEL_ID", "1")
    import bot
    names = [c.name for c in bot.tree.get_commands()]
    assert names == ["niveau-armes"]                                       # un seul arbre, une seule commande
    assert bot.client.on_message.__module__ == "bot" and bot.client.on_ready.__module__ == "bot"
    assert not hasattr(bot, "niveau")                                      # ancien /niveau retiré


def test_armes_memes_attaques_que_le_moteur_de_chasse():
    """Une stat d'unité doit être la même dans toutes les commandes du bot."""
    import hunt_mc
    names = {"jsn": "JSN", "sn": "SN", "ne": "NE", "js": "JS", "s": "S", "c": "C", "ce": "CE", "a": "A", "ae": "AE",
             "se": "SE", "tk": "Tk", "tke": "TkE", "tu": "Tu", "tue": "TuE"}
    assert set(names) == set(hunt_mc.UNITS)
    for key, abbr in names.items():
        assert na.DATA.unit(abbr).attack == hunt_mc.UNITS[key][1], abbr
