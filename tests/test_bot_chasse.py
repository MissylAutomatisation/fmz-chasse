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


def test_pertes_en_equivalent_jsn():
    """Une perte vaut son temps de ponte divisé par celui d'une JSN (page Reine) : 1 SN = 1,5, 1 JS = 2,5."""
    assert risque.jsn_equiv({"jsn": 10}) == 10
    assert risque.jsn_equiv({"sn": 2, "js": 3}) == pytest.approx(2 * 1.5 + 3 * 740 / 300)
    assert set(risque.hunt_mc.PONTE) == set(risque.hunt_mc.UNITS)


def test_plus_de_jsn_jamais_plus_de_pertes():
    """Des JSN en plus meurent à la place des SN, NE et JS : plus d'unités mortes, mais moins de ponte perdue
    (armée du salon chasse-bot, 13 700 cm²)."""
    reste = {"sn": 188, "ne": 136, "js": 2367, "s": 1864, "a": 9126, "ae": 3101, "se": 915}
    sans, avec = {"jsn": 558, **reste}, {"jsn": 1836, **reste}
    _, moy_sans, pire_sans, _, unites_sans = risque.stats(sans, 17530, 13700, 8, 7, 2000)
    _, moy_avec, pire_avec, _, unites_avec = risque.stats(avec, 17530, 13700, 8, 7, 2000)
    assert sum(unites_avec.values()) > sum(unites_sans.values())
    assert moy_avec < moy_sans and pire_avec < pire_sans


def test_risque_comme_le_calcul_du_04_10():
    """70 cm² à 2 770 TDC (1 208 JSN + 99 SN, Armes 1, Bouclier 2) : ~7,5 % ; 60 cm² : ~1 %."""
    army = {"jsn": 1208, "sn": 99}
    assert 5 < risque.stats(army, 2770, 70, 1, 2, 3000)[0] < 10
    assert risque.stats(army, 2770, 60, 1, 2, 3000)[0] < 2


def test_tableau_pret_pour_discord():
    """Seulement les lignes utiles (🛡 📈 ⭐ 🔥), avec la FDF, sans prochaines chasses."""
    out = risque.answer("1 208 JSN + 99 SN, Armes 1, Bouclier 2, TDC 2 770")
    lines = out.splitlines()
    assert lines[0] == lines[-1] == "```"
    assert lines[2] == "   (1 208 JSN + 99 SN, Armes 1, Bouclier 2, TDC 2 770)"
    assert lines[3] == "   (FDF : 4 531)"                                  # (1 208 × 3 + 99 × 5) × 1,1
    rows = lines[7:lines.index("🛡 min. pertes  📈 meilleur cm²/perte")]
    sizes = [int(r.split()[0]) for r in rows]
    assert sizes == sorted(sizes) and 55 <= sizes[0] <= 64 and 2 <= len(rows) <= 4
    assert all(len(r.split("|")) == 5 for r in rows)
    roles = "".join(r.split()[-1] for r in rows)
    assert sorted(roles) == sorted("🛡📈⭐🔥") and "🛡" in rows[0]
    assert "📅" not in out and lines[-3].startswith("⭐ opti") and lines[-2].startswith("Pertes en équiv. JSN")


def test_fdf_avec_bonus_armes():
    assert risque.fdf({"jsn": 1208, "sn": 99}, 0) == 4119
    assert risque.fdf({"js": 100}, 5) == 1500


def test_etoile_sur_la_plus_grosse_chasse_rentable():
    """1 027 JSN + 104 SN, Armes 2, Bouclier 2, TDC 2 826 : ⭐ vers 70-75 cm², 🔥 au moins aussi gros."""
    rows = risque.key_rows({"jsn": 1027, "sn": 104}, 2, 2, 2826)
    star = next(r[0] for r in rows if "⭐" in r[5])
    fire = next(r[0] for r in rows if "🔥" in r[5])
    assert 66 <= star <= 78 <= fire + 4 and fire >= star


def test_pas_de_plafond_de_taille():
    """Grosse armée (RC du salon chasse-bot) : ⭐ au-delà de 5 000 cm², jamais sur une chasse perdue."""
    army = {"jsn": 3905, "sn": 502, "js": 4398, "s": 1372, "a": 4642}
    rows = risque.key_rows(army, 7, 7, 16154)
    star = next(r for r in rows if "⭐" in r[5])
    assert star[0] > 5000 and star[3] < risque.jsn_equiv(army)


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
    normal, rep30 = risque.answer(text), risque.answer(text + ", réplique 30")
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
    """Plus grosse chasse au pire cas ≤ 100 : une ligne, sans colonne réplique."""
    out = risque.answer("1 208 JSN + 99 SN, Armes 1, Bouclier 2, TDC 2 770, perte 100")
    lines = out.splitlines()
    assert lines[0] == lines[-1] == "```" and lines[1] == "🎯 Chasse pour 100 pertes max (équiv. JSN)"
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
    """Pire cas : le détail exact du pire combat en unités, son équivalent JSN = le pire cas, même calcul sur 1 ou 4 cœurs."""
    army = {"jsn": 80, "sn": 1200}
    _, _, worst, _, units = risque.stats(army, 2770, 273, 1, 2, 5000)
    assert round(risque.jsn_equiv(units)) == worst and units["jsn"] == 80 and units["sn"] > 0
    assert risque._chunk(army, 2770, 273, 1, 2, 1, 0, 5000)[2] == units
    out = risque.answer("80 JSN + 1 200 SN, Armes 1, Bouclier 2, TDC 2 770, perte 100").splitlines()
    assert out[-9].split("|")[-1].strip().isdigit() and out[-8].startswith("Pire cas : 80 JSN + ")


def test_perte_jamais_une_chasse_perdue():
    """Limite au-delà de l'armée : plafonnée à l'armée moins 1, la chasse reste gagnée."""
    out = risque.answer("1 208 JSN + 99 SN, Armes 1, Bouclier 2, TDC 2 770, perte 100000").splitlines()
    assert out[1] == "🎯 Chasse pour 1 355 pertes max (équiv. JSN)"
    row = next(l for l in out if "cm²  |" in l or " cm² |" in l)
    assert int(row.split()[0]) < 1000 and int(row.split("|")[-1]) <= 1355


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
    ("Artilleuses", 4, 5, 22400),
])
def test_armes_productions_du_menu(produced, level, nxt, target):
    r = na.analyse_armes(ARMY_REF, produced)
    assert (r["fdf_hb"], r["niveau_max"], r["niveau_suivant"], r["cible_hb"]) == (10765, level, nxt, target)


def test_armes_tableau_de_controle_des_seuils():
    table = {"Jeune Soldate Naine": [480, 1056, 2304, 4992, 10752, 23040],
             "Jeune Soldate": [649, 1428, 3114, 6746, 14530, 31136],
             "Tank": [1420, 3123, 6813, 14762, 31794, 68130],
             "Tueuse d’élite": [964, 2120, 4625, 10021, 21583, 46249],
             "Artilleuse": [1000, 2200, 4800, 10400, 22400, 48000]}
    for name, targets in table.items():
        unit = na.DATA.unit(name)
        assert [na.threshold(na.DATA, unit, n, c) for n, c in na.DATA.costs[:6]] == targets
    assert na.DATA.costs[-1] == (50, 45035996273704960)


def test_armes_menu_contient_les_artilleuses():
    view = na.UnitView(1, {"Jeune Soldate": 1}, na.Sessions(), {})
    select = next(i for i in view.children if isinstance(i, na.UnitSelect))
    assert "Artilleuse" in [o.value for o in select.options]


def test_armes_artilleuses_juste_apres_les_js_dans_le_menu():
    assert [label for label, _, _ in na.CHOICES] == [
        "Jeunes Soldates Naines", "Jeunes Soldates", "Artilleuses", "Tanks", "Tueuses d’élite"]


def test_armes_affichage():
    embed = na.result_embed(na.parse_army(ARMY_REF), "JS")
    assert embed.title == "Armes 4 — Niveau maximal rentable"
    assert embed.description == ("Actuel : **10 765 HB**\nCible Armes 5 : **14 530 HB**\nManque : **3 765 HB**\n\n"
                                 "**Production : Jeune Soldate · HB = attaque hors bonus**")
    top = na.result_embed({"Tank": 10 ** 21}, "JSN")
    assert top.title == "Armes 50 ou plus — Niveau maximal rentable"
    assert "Tous les niveaux de la BDD sont rentables" in top.description


ARMY_ONLY = ("8 468 Jeunes Soldates Naines, 1 322 Soldates Naines, 219 Naines d’Elites, 10 552 Jeunes Soldates, "
             "850 Soldates, 44 Soldates d’élites.")


@pytest.mark.parametrize("text, expected", [
    (ARMY_ONLY, {"jsn": 8468, "sn": 1322, "ne": 219, "js": 10552, "s": 850, "se": 44}),
    ("Armée : 600 JS, 43 S", {"js": 600, "s": 43}),
    ("Jeune Soldate Naine 1 208\nSoldate 43", {"jsn": 1208, "s": 43}),
    ("1 208 JSN + 99 SN, Armes 1", None),
    ("600 JSN, Bouclier 2", None),
    ("600 JSN, TDC 300", None),
    ("600 JSN, perte 100", None),
    ("600 JSN, réplique 30", None),
    ("bonjour", None),
])
def test_salon_armee_seule(text, expected):
    assert risque.army_only(text) == expected


def test_armee_n_est_pas_armes():
    assert risque.parse("Armée : 600 JS, 43 S, Armes 1, TDC 100") == ({"js": 600, "s": 43}, 1, 0, 100)


def test_armes_armee_du_salon_convertie():
    army = na.from_hunt_army(risque.army_only(ARMY_REF))
    assert army == na.parse_army(ARMY_REF)


class _ChannelMessage:
    def __init__(self, author_id, channel_id, content):
        self.author = SimpleNamespace(id=author_id)
        self.channel = SimpleNamespace(id=channel_id)
        self.content = content
        self.replies = []

    async def reply(self, content=None, **kwargs):
        self.replies.append((content, kwargs))
        sent = _Message()
        return sent


def test_armes_salon_question_puis_nom_de_l_unite():
    async def scenario():
        na.SESSIONS.pending.clear()
        emojis = SimpleNamespace(values={}, ensure=lambda: _record([], (), {}))
        msg = _ChannelMessage(1, 10, ARMY_REF)
        await na.ask_in_channel(msg, risque.army_only(ARMY_REF), emojis, silent=True)
        assert "Quelle unité" in msg.replies[0][0] and msg.replies[0][1]["silent"]
        view = na.SESSIONS.pending[1]
        view.message = _Message()
        # autre salon, autre joueur ou texte qui n'est pas une unité : ignorés
        assert not await na.answer_unit_name(_ChannelMessage(1, 11, "JS"), True)
        assert not await na.answer_unit_name(_ChannelMessage(2, 10, "JS"), True)
        assert not await na.answer_unit_name(_ChannelMessage(1, 10, "salut"), True)
        assert await na.answer_unit_name(_ChannelMessage(1, 10, "Jeunes Soldates"), True)
        assert view.message.edits[-1]["embed"].title.startswith("Armes 4 —")
        assert 1 not in na.SESSIONS.pending

    asyncio.run(scenario())


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
    response = SimpleNamespace(send_message=lambda *a, **k: _record(sent, a, k), defer=lambda: _record([], (), {}))
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
    os.environ["FICHES_DB"] = ":memory:"                                   # pas de fichier de base pendant les tests
    import bot
    names = [c.name for c in bot.tree.get_commands()]
    assert sorted(names) == ["niveau-armes", "niveau-joueur", "renta"]             # un seul arbre pour toutes les commandes
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


# --- Salon profil (ov, Champignonnière, Étable à pucerons) ---
import re  # noqa: E402

import profil  # noqa: E402


@pytest.mark.parametrize("text, expected", [
    ("ov 1234567 champi 12 puceron 8", {"ov": 1234567, "champi": 12, "puceron": 8}),
    ("Ouvrières : 1 234 567, Champignonnière 12, étable à pucerons 8", {"ov": 1234567, "champi": 12, "puceron": 8}),
    ("ouvriere 1.234.567 champignons niv 9 pucerons lvl 7", {"ov": 1234567, "champi": 9, "puceron": 7}),
    ("OVS 500000 etable 4", {"ov": 500000, "puceron": 4}),
    ("12 champi 8 puceron", {"champi": 12, "puceron": 8}),
    ("champi 13", {"champi": 13}),
    ("ov 1234567 champi", {"ov": 1234567}),
    ("pseudo Missyl ov 1234567", {"pseudo": "Missyl", "ov": 1234567}),
    ("ov 500000 IG : Grim_Le-Fourbe champi 3", {"pseudo": "Grim_Le-Fourbe", "ov": 500000, "champi": 3}),
    ("id in game ovni42", {"pseudo": "ovni42"}),
    ("Pseudo: Élodie", {"pseudo": "Élodie"}),
    ("DogGyneco ov 63981 champi 12 puceron 0", {"pseudo": "DogGyneco", "ov": 63981, "champi": 12, "puceron": 0}),
    ("Grim_42 : champi 5", {"pseudo": "Grim_42", "champi": 5}),
    ("Ouvrières 5000 champi 3", {"ov": 5000, "champi": 3}),
    ("Étable à pucerons 8", {"puceron": 8}),
])
def test_profil_lecture(text, expected):
    assert profil.parse(text) == expected


def test_profil_message_incompris():
    with pytest.raises(profil.ProfilError):
        profil.parse("bonjour")
    with pytest.raises(profil.ProfilError):
        profil.parse("DogGyneco")                              # un mot seul n'est pas un profil


class FakeWorksheet:
    def __init__(self):
        self.rows = [[]]

    def get_all_values(self):
        return [list(r) for r in self.rows]

    def update(self, range_name, values, value_input_option=None):
        i = int(range_name[1:]) - 1
        self.rows += [[] for _ in range(i + 1 - len(self.rows))]
        self.rows[i] = [str(v) for v in values[0]]

    def append_row(self, row, value_input_option=None, table_range=None):
        self.rows.append([str(v) for v in row])

    def batch_update(self, data, value_input_option=None):
        for cell in data:
            m = re.fullmatch(r"([A-Z]+)(\d+)", cell["range"])
            c = sum((ord(ch) - 64) * 26 ** k for k, ch in enumerate(reversed(m[1]))) - 1
            r = int(m[2]) - 1
            row = self.rows[r]
            row += [""] * (c + 1 - len(row))
            row[c] = str(cell["values"][0][0])


def test_profil_une_ligne_par_joueur_mise_a_jour_partielle():
    sheet = profil.ProfilSheet.__new__(profil.ProfilSheet)
    sheet.ws = FakeWorksheet()
    sheet.save(1, "A", {"ov": 1000, "champi": 5, "puceron": 3})
    sheet.save(2, "B", {"ov": 2000})
    sheet.save(1, "A2", {"champi": 6, "pseudo": "Missyl"})
    rows = sheet.ws.rows
    assert rows[0] == profil.HEADER and len(rows) == 3
    assert rows[1][:6] == ["A2", "Missyl", "1", "1000", "6", "3"]
    assert rows[2][:6] == ["B", "", "2", "2000", "", ""]


def test_profil_colonnes_retrouvees_par_titre():
    """Colonnes déplacées et colonne ajoutée à la main : le bot retrouve les siennes et ne touche pas aux autres."""
    sheet = profil.ProfilSheet.__new__(profil.ProfilSheet)
    sheet.ws = FakeWorksheet()
    sheet.ws.rows = [["ID Discord", "Notes", "Nom Discord", "Ouvrières", "Mis à jour", "Champignonnière",
                      "Étable à pucerons", "ID In Game"],
                     ["7", "chef", "Ancien", "10", "", "1", "1", ""]]
    sheet.save(7, "Nouveau", {"ov": 99, "pseudo": "Missyl"})
    row = sheet.ws.rows[1]
    assert row[0] == "7" and row[1] == "chef" and row[2] == "Nouveau" and row[3] == "99"
    assert row[5] == "1" and row[7] == "Missyl"
    sheet.save(8, "Autre", {"champi": 4})
    assert sheet.ws.rows[2][0] == "8" and sheet.ws.rows[2][2] == "Autre" and sheet.ws.rows[2][5] == "4"


def test_profil_valeur_en_baisse_remplace_l_ancienne():
    """Ouvrières perdues ou bâtiment rasé : la dernière valeur donnée gagne, même plus basse."""
    sheet = profil.ProfilSheet.__new__(profil.ProfilSheet)
    sheet.ws = FakeWorksheet()
    sheet.save(1, "A", {"ov": 63981, "champi": 12})
    sheet.save(1, "A", {"ov": 40000, "champi": 0})
    assert sheet.ws.rows[1][3:5] == ["40000", "0"]


def test_profil_colonne_manquante_ajoutee_au_bout():
    sheet = profil.ProfilSheet.__new__(profil.ProfilSheet)
    sheet.ws = FakeWorksheet()
    sheet.ws.rows = [["Nom Discord", "ID Discord", "Ouvrières", "Champignonnière", "Étable à pucerons", "Mis à jour"],
                     ["A", "1", "1000", "5", "3", "01/01/2026 10:00"]]
    sheet.save(1, "A", {"pseudo": "Missyl"})
    assert sheet.ws.rows[0][6] == "ID In Game"
    assert sheet.ws.rows[1][:5] == ["A", "1", "1000", "5", "3"] and sheet.ws.rows[1][6] == "Missyl"


def test_profil_entete_colonnes():
    assert profil.HEADER[:3] == ["Nom Discord", "ID In Game", "ID Discord"]


def test_profil_resume_avec_pseudo():
    assert profil.summary({"pseudo": "Missyl", "ov": 1234567}) == "ID In Game Missyl · Ouvrières 1 234 567"


# --- Export CSV du sheet Data OUAF (/niveau-joueur) ---
def test_export_niveau_joueur():
    joueurs = [{"id": 426, "pseudo": "Sirius", "alliance": "OUAF"},
               {"id": 412, "pseudo": "Krokmou", "alliance": "OUAF"},
               {"id": 434, "pseudo": "Bull", "alliance": "OUAF"},
               {"id": 7, "pseudo": "Autre", "alliance": "LCN"}]
    fiches = [{"ID In Game": "Sirius", "Ouvrières": "100\u202f191", "Champignonnière": "16", "Étable à pucerons": "4",
               "VC": 3, "VA": 5},
              {"ID In Game": "krokmou", "Ouvrières": "55 000", "Champignonnière": "12", "Étable à pucerons": ""},
              {"ID In Game": "Inconnu", "Ouvrières": "", "Champignonnière": "3", "Étable à pucerons": "1"},
              {"ID In Game": "", "Ouvrières": "9"}]
    lignes = profil.lignes_export(fiches, joueurs, "OUAF")
    assert lignes == [[434, "Bull", 0, 0, 0, 0, 0], ["", "Inconnu", 1, 3, 0, 0, 0],
                      [412, "Krokmou", 0, 12, 55000, 0, 0], [426, "Sirius", 4, 16, 100191, 3, 5]]
    assert profil.texte_csv(lignes).splitlines()[:2] == ["player_id,pseudo,etable_puceron,champi,ouvriere,vc,va",
                                                          "434,Bull,0,0,0,0,0"]


def test_export_sans_api():
    ancien = profil.joueurs_api
    profil.joueurs_api = lambda: (_ for _ in ()).throw(OSError("hors ligne"))
    try:
        texte, ok = profil.export([{"Nom Discord": "x", "ID In Game": "Sirius", "Champignonnière": 16}], "OUAF")
    finally:
        profil.joueurs_api = ancien
    assert not ok and texte.splitlines()[1] == ",Sirius,0,16,0,0,0"


import renta_puceron as rp  # noqa: E402


@pytest.mark.parametrize("text", ["ov 15000", "OV 15 000", "ov: 15.000", "ouvrières 15000", "15000 ov", "15 000 OV", "Ouv 15000", "15000 ouv"])
def test_puceron_lecture_message(text):
    assert rp.parse_workers_message(text) == 15000


@pytest.mark.parametrize("text", ["j'ai 15000 ov", "ov 15k", "ov", "948 JSN, Armes 2, Bouclier 2, TDC 2 148"])
def test_puceron_message_ignore(text):
    assert rp.parse_workers_message(text) is None


def test_puceron_passage_marginal():
    r = rp.calculate_pucerons(15000)
    assert (r.comparison_from_level, r.level, r.sacrificed_workers, r.remaining_workers) == (1, 2, 640, 14360)
    assert (r.capacity_before_twice, r.capacity_after_twice, r.capacity_gain_twice) == (315000, 315920, 920)


def test_puceron_seuils():
    assert rp.calculate_pucerons(11760).level == 0
    r = rp.calculate_pucerons(11761)
    assert r.level == 1 and r.capacity_gain_twice == 1                       # gain exact de 0,5 rss


@pytest.mark.parametrize("workers, level, target, cost, remaining", [
    (15000, 0, 2, 1200, 13800),
    (14081, 0, 1, 560, 13521),                                                 # le sacrifice initial bloque le niveau 2
    (21_000_000, 0, 11, 655280, 20344720),
    (15000, 3, 3, 0, 15000),                                                   # jamais de baisse de niveau
])
def test_puceron_niveau_actuel(workers, level, target, cost, remaining):
    r = rp.calculate_pucerons(workers, level)
    assert (r.projected_level, r.projected_cost, r.projected_remaining_workers) == (target, cost, remaining)


def test_puceron_niveau_actuel_capacite():
    r = rp.calculate_pucerons(15000, 0)
    assert (r.current_capacity_twice, r.projected_capacity_twice, r.projected_gain_twice) == (300000, 303600, 3600)
    assert rp.calculate_pucerons(21_000_000).level == 12


def test_puceron_commande_enregistree():
    from discord import app_commands
    client = rp.discord.Client(intents=rp.discord.Intents.default())
    tree = app_commands.CommandTree(client)
    rp.setup(tree)
    assert tree.get_command("renta").get_command("puceron") is not None


# --- Fiches des joueurs (base SQLite, copiée dans le sheet) ---
import fiches  # noqa: E402

ARMEE_OUAF = ("1 425 Jeunes Soldates Naines, 359 Soldates Naines, 100 Naines d’Elites, 5 601 Jeunes Soldates, "
              "1 434 Soldates, 4 725 Artilleuses, 303 Artilleuses d’élites, 177 Soldates d’élites, armes 8, bouclier 7")


def test_profil_armee_armes_bouclier():
    v = profil.parse(ARMEE_OUAF)
    assert v == {"armes": 8, "bouclier": 7, "armee": {"jsn": 1425, "sn": 359, "ne": 100, "js": 5601, "s": 1434,
                                                       "a": 4725, "ae": 303, "se": 177}}
    assert "Armes 8 · Bouclier 7 · Armée 1 425 JSN + 359 SN" in profil.summary(v)
    assert profil.parse("Missyl 1425 JSN armes 8") == {"pseudo": "Missyl", "armes": 8, "armee": {"jsn": 1425}}
    assert profil.parse("pseudo Missyl ov 1 234 567 champi 12 puceron 8") == {
        "pseudo": "Missyl", "ov": 1234567, "champi": 12, "puceron": 8}                 # rien de plus qu'avant


def test_profil_entete_avec_armee():
    assert profil.HEADER[-5:-2] == ["Armes", "Bouclier", "Armée"]
    assert profil.sheet_value("armee", {"jsn": 1425, "sn": 359}) == "1 425 JSN + 359 SN"
    assert profil.army_of("1 425 JSN + 359 SN") == {"jsn": 1425, "sn": 359}


def test_fiche_seuls_les_champs_donnes_changent():
    db = fiches.Fiches(":memory:")
    db.save(1, "Martin", {"pseudo": "Missyl", "ov": 100, "armes": 8, "bouclier": 7, "armee": {"jsn": 10}},
            date="19/10/2026 14:00")
    db.save(1, "Martin", {"armee": {"jsn": 20, "sn": 5}}, date="19/10/2026 15:00")      # la dernière armée fait foi
    f = db.get(1)
    assert (f["pseudo"], f["ov"], f["armes"], f["bouclier"]) == ("Missyl", 100, 8, 7)
    assert f["armee"] == {"jsn": 20, "sn": 5} and f["armee_maj"] == "19/10/2026 15:00"
    db.save(1, "Martin", {"armes": 9}, date="20/10/2026 10:00")
    assert db.get(1)["armee_maj"] == "19/10/2026 15:00"                                # date de l'armée inchangée
    assert db.get(2) is None and len(db.all()) == 1


def test_fiches_importees_depuis_le_sheet():
    db = fiches.Fiches(":memory:")
    n = db.import_sheet([{"Nom Discord": "m", "ID In Game": "Missyl", "ID Discord": "42", "Ouvrières": "1 234",
                          "Champignonnière": "12", "Étable à pucerons": "", "Mis à jour": "18/10/2026 09:00",
                          "Armes": "8", "Armée": "1 425 JSN + 359 SN"},
                         {"Nom Discord": "sans id", "ID Discord": ""}])
    f = db.get(42)
    assert n == 1 and (f["pseudo"], f["ov"], f["champi"], f["puceron"], f["armes"]) == ("Missyl", 1234, 12, None, 8)
    assert f["armee"] == {"jsn": 1425, "sn": 359} and f["armee_maj"] == "18/10/2026 09:00"


def test_chasse_avec_la_fiche(monkeypatch):
    vu = {}
    monkeypatch.setattr(risque, "table", lambda army, armes, bouclier, tdc, rep=10: vu.update(
        army=army, armes=armes, bouclier=bouclier, tdc=tdc) or "TABLEAU")
    fiche = {"armee": {"jsn": 1425, "sn": 359}, "armee_maj": "19/10/2026 14:02", "armes": 8, "bouclier": 7}
    assert risque.answer("TDC 2 770", fiche) == ("📋 Pris dans ta fiche : armée du 19/10/2026 14:02, Armes, Bouclier\n"
                                                 "TABLEAU")
    assert vu == {"army": {"jsn": 1425, "sn": 359}, "armes": 8, "bouclier": 7, "tdc": 2770}
    assert risque.answer("500 JSN, TDC 2 770", fiche) == "📋 Pris dans ta fiche : Armes, Bouclier\nTABLEAU"
    assert vu["army"] == {"jsn": 500}                                                   # l'armée collée passe avant
    assert risque.answer("500 JSN, Armes 2, Bouclier 0, TDC 2 770", fiche) == "TABLEAU"
    assert (vu["armes"], vu["bouclier"]) == (2, 0)
    assert risque.answer("500 JSN, TDC 2 770") == "TABLEAU" and vu["armes"] == 0        # sans fiche : comme avant
    assert risque.answer("TDC 2 770").startswith("❌ Aucune unité")
    assert "salon profil" in risque.answer("TDC 2 770", {"armes": 8})


def test_lecture_partielle():
    assert risque.parse_partial("TDC 2 770") == (None, None, None, 2770)
    assert risque.read("500 JSN, armes 3, réplique 30") == {"rep": 30, "cap": None, "vc": None, "va": None,
                                                            "army": {"jsn": 500}, "armes": 3, "bouclier": None,
                                                            "tdc": None}


def test_profil_vc():
    assert profil.parse("vc 3") == {"vc": 3}
    assert profil.parse("Vitesse de chasse 3 armes 8") == {"vc": 3, "armes": 8}
    assert profil.parse("VC 3") == {"vc": 3}                                             # pas un pseudo
    assert profil.HEADER[-2:] == ["VC", "VA"]
    db = fiches.Fiches(":memory:")
    db.save(1, "x", {"vc": 3})
    assert db.get(1)["vc"] == 3


@pytest.mark.parametrize("text, expected", [
    ("Arme 9 bouclier 6", {"armes": 9, "bouclier": 6}),
    ("Armes 9", {"armes": 9}),
    ("Bouclier 6 armes 9", {"armes": 9, "bouclier": 6}),
    ("JSN 1425 SN 359", {"armee": {"jsn": 1425, "sn": 359}}),
    ("Missyl arme 9", {"pseudo": "Missyl", "armes": 9}),
])
def test_profil_mot_cle_jamais_pris_pour_pseudo(text, expected):
    assert profil.parse(text) == expected


@pytest.mark.parametrize("text, va", [
    ("va 5", 5), ("VA 5", 5), ("Vitesse d'attaque 5", 5), ("vitesse d’attaque 5", 5), ("ça va", None),
    ("5 va", None),
])
def test_va_lecture(text, va):
    assert risque.speeds(text)[1] == va


def test_va_fiche():
    assert profil.parse("va 5 vc 3") == {"va": 5, "vc": 3}
    assert profil.parse("VA 5") == {"va": 5}                                             # pas un pseudo
    assert risque.read("TDC 2 770 va 5")["va"] == 5 and risque.read("TDC 2 770 va 5")["tdc"] == 2770
    assert risque.army_only("500 JSN va 5") is None
    db = fiches.Fiches(":memory:")
    db.save(1, "x", {"va": 5})
    assert db.get(1)["va"] == 5


def test_base_ancienne_completee(tmp_path):
    """Une base créée avant la VC et la VA reçoit les colonnes au démarrage."""
    import sqlite3
    path = str(tmp_path / "f.db")
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE fiches (discord_id TEXT PRIMARY KEY, nom TEXT, pseudo TEXT, ov INTEGER, champi INTEGER, "
                "puceron INTEGER, armes INTEGER, bouclier INTEGER, armee TEXT, armee_maj TEXT, maj TEXT)")
    old.commit()
    old.close()
    db = fiches.Fiches(path)
    db.save(1, "x", {"vc": 2, "va": 4})
    assert (db.get(1)["vc"], db.get(1)["va"]) == (2, 4)


def test_vc_gardee_mais_une_seule_chasse(monkeypatch):
    vu = []
    monkeypatch.setattr(risque, "table", lambda *a, **k: vu.append((a, k)) or "TABLEAU")
    assert risque.answer("500 JSN vc 3 va 5 TDC 2 770", {"vc": 6}) == "TABLEAU"
    assert vu == [(({"jsn": 500}, 0, 0, 2770), {"rep": 10})]                           # calcul normal, 1 chasse
    found = risque.read("500 JSN vc 3 va 5 TDC 2 770")
    assert (found["vc"], found["va"], found["tdc"]) == (3, 5, 2770)
