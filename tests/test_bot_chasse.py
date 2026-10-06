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


# --- /niveau : niveaux rentables d'Armes et de Bouclier ---
import niveau  # noqa: E402

ARMY_05_10 = "989 JSN + 252 SN + 2 NE + 240 JS + 3 S"


def test_niveau_commande_reconnue():
    assert niveau.is_command("/niveau 100 JSN, Armes 1")
    assert niveau.is_command("Niveau 100 JSN")
    assert not niveau.is_command("100 JSN, Armes 1, TDC 500")


def test_niveau_ratio_armes_3_en_js():
    """Armée du 05/10 (FDF 6 686) : Armes 3 = +669 contre 320 OV × 60 s de ponte de JS à Armes 2."""
    army, *_ = risque.parse(ARMY_05_10, need_tdc=False)
    assert niveau.base_fdf(army) == 6686
    rate = niveau.per_second(niveau.base_fdf, {"js": 1})
    assert niveau.ratio(668.6, rate, 3) == pytest.approx(668.6 / (320 * 60 * 10 / 740 * 1.2))


def test_niveau_max_rentable_par_unite():
    army, *_ = risque.parse(ARMY_05_10, need_tdc=False)
    rows = {name: (lvl, nxt) for name, lvl, nxt in niveau.armes_rows(army)}
    assert rows["JS"][0] == 3 and 0.95 < rows["JS"][1] < 1         # Armes 4 tout juste pas rentable en JS
    assert rows["Armée"][0] == 4                                   # mélange de l'armée : moins de FDF par heure
    assert rows["Tk"][0] < rows["JS"][0] < rows["JSN"][0]          # plus l'unité frappe vite, moins Armes vaut
    for lvl, nxt in rows.values():
        assert nxt < 1


def test_niveau_vie_arrondie_comme_toolzzz():
    assert [niveau.life("jsn", b) for b in range(6)] == [8, 9, 10, 10, 11, 12]
    assert niveau.life("ne", 5) == 13 + 7                          # 6,5 arrondi vers le haut


def test_niveau_bouclier_compare_a_la_jsn():
    army = {"jsn": 1000}
    # Bouclier 1 : +1 000 PV contre 80 OV × 60 s / 300 s = 16 JSN de 8 PV
    assert niveau.bouclier_ratio(army, 0, 1) == pytest.approx(1000 / (16 * 8))
    assert niveau.bouclier_ratio(army, 2, 3) == 0                  # JSN : 10 PV au Bouclier 2 et 3
    lvl, nxt = niveau.bouclier_level(army)
    assert nxt < 1 and any(niveau.bouclier_ratio(army, lvl - j, lvl) >= 1 for j in (1, 2, 3))


def test_niveau_reponse_discord():
    out = niveau.answer("/niveau " + ARMY_05_10 + ", Armes 2")
    assert out.startswith("```") and out.endswith("```")
    assert "(tu es à 2)" in out and " JS          | Armes 3" in out and "Bouclier " in out
    assert niveau.answer("/niveau Armes 2").startswith("❌ Aucune unité")
