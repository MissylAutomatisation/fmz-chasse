"""Risque selon la taille de chasse : lit « 1 208 JSN + 99 SN, Armes 1, Bouclier 2, TDC 2 770 » et rend le tableau.

Moteur : hunt_mc.py (tirages de prédateurs réalistes, repris de fourmizzz-zero-perte.pages.dev).
« Réplique > 10 % » = au 1er tour, l'attaque ne dépasse pas 3 fois la vie des prédateurs (> 30 % : 2 fois, > 50 % :
1,5 fois). Par défaut 10 % ; « réplique 30 » ou « réplique 50 » dans le message change le seuil compté.
"""
import itertools
import math
import logging
import os
import random
import re
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

try:
    import hunt_mc                                    # sur le Pi : copié à côté de ce fichier
except ImportError:                                   # dans le projet : tools/hunt_mc.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
    import hunt_mc

NUM = r"\d{1,3}(?:[ \u00a0\u202f.']\d{3})+|\d+"    # 1 208, 1 208 (espace insécable), 1.208, 1'208, 1208
SEP = r"[\s:=]*(?:niveau|niv|lvl|lv)?\.?[\s:=]*"     # « Armes 1 », « armes: 1 », « Armes niv. 1 », « tdc=2770 »
ELITE = r"\s+d\W?\s*[ée]lites?"                       # « d'élite », « d’Elites », « d elite »
# (mot, unité, sensible à la casse) ; les noms longs d'abord (« Jeunes Soldates Naines » contient « Soldates Naines »...)
UNIT_WORDS = [(r"jeunes?\s+soldates?\s+naines?", "jsn", False), (r"jeunes?\s+soldates?", "js", False),
              (r"soldates?\s+naines?", "sn", False), (r"naines?" + ELITE, "ne", False),
              (r"soldates?" + ELITE, "se", False), (r"concierges?" + ELITE, "ce", False),
              (r"artilleuses?" + ELITE, "ae", False), (r"tanks?" + ELITE, "tke", False),
              (r"tueuses?" + ELITE, "tue", False), (r"soldates?", "s", False), (r"concierges?", "c", False),
              (r"artilleuses?", "a", False), (r"tanks?", "tk", False), (r"tueuses?", "tu", False),
              (r"jsns?", "jsn", False), (r"sns?", "sn", False), (r"nes?", "ne", False), (r"jss?", "js", False),
              (r"ses?", "se", False), (r"ces?", "ce", False), (r"aes?", "ae", False), (r"tkes?", "tke", False),
              (r"tks?", "tk", False), (r"tues?", "tue", False), (r"tus?", "tu", False),
              (r"S", "s", True), (r"C", "c", True), (r"A", "a", True)]   # lettres seules : en majuscule seulement
UNIT_ORDER = list(hunt_mc.UNITS)                     # affichage dans l'ordre du jeu
# lettres seules : « armes1 » ; « Armée » n'est pas « Armes »
LEVEL_WORDS = [(r"bouc[^\W\d_]*(?:\s+thoraciques?)?", "bouclier"), (r"arm(?![ée]es?\b)[^\W\d_]*", "armes")]
TDC_WORDS = r"tdc|terrains?(?:\s+de\s+chasse)?|cm²|cm2|cm"
TARGETS = (1, 2, 5, 7.5, 10, 15, 20)                          # niveaux de risque (%) des tailles repères
STARS = ((0.85, "⭐"), (0.80, "🔥"))               # plus grosse chasse qui garde 85 % / 80 % du meilleur cm²/perte
BUCKETS = 4                                          # tranches égales de 0 à la limite, sous « perte XXX »
REPLIQUES = {10: 3, 30: 2, 50: 1.5}                  # réplique comptée (%) -> l'attaque doit dépasser ce multiple de la vie
REPLIQUE_WORDS = r"r[ée]pli(?:que)?s?\s*[:=]?\s*(\d+)\s*%?"   # « réplique 30 », « Replique: 50 % », « répli 30 »
PERTE_WORDS = r"pertes?(?:\s+max(?:imum|imales?|i)?)?"      # « perte 100 », « pertes max 100 », « 100 pertes »
VC_WORDS = r"vc|vitesses?\s+de\s+chasses?"           # « vc 2 », « Vitesse de chasse 2 » : VC + 1 chasses simultanées
VA_WORDS = r"va|vitesses?\s+d\W?\s*attaques?"         # « va 5 », « Vitesse d'attaque 5 » : gardée dans la fiche seulement
HUNTS_WORDS = r"(?<!de )chasses?|multi[\s-]?chasses?"   # « 3 chasses », « chasses 3 » ; pas « terrain de chasse »
MAX_HUNTS = 20
MIN_HUNT_SHARE = 30                                  # taille mini d'une chasse en multi : 30 % du TDC (Calystène)
CHOICE_DRAWS = 1000                                  # tirages pour choisir le nombre de chasses (le tableau en garde 5 000)


class ParseError(ValueError):
    pass


def to_int(text):
    return int(re.sub(r"[^\d]", "", text))


def take(text, word, num, after_first, case=False, both=True):
    """Cherche « mot nombre » et « nombre mot » (ordre préféré en premier). Renvoie (nombres trouvés, texte sans eux)."""
    # « mot nombre » : le nombre peut être collé au mot (« armes1 »)
    after, before = rf"\b(?:{word})(?![^\W\d_]){SEP}({num})", rf"(?<![\d.])({num})\s*(?:{word})\b"
    flags = 0 if case else re.I
    found = []
    for pattern in ((after, before) if after_first else (before, after))[:2 if both else 1]:
        def keep(m):
            found.append(to_int(m.group(1)))
            return " ; "                              # coupe le texte : le nombre ne resservira pas
        text = re.sub(pattern, keep, text, flags=flags)
    return found, text


def parse_partial(text):
    """Texte libre -> (armée {"jsn": n, ...}, armes, bouclier, tdc), None pour chaque élément absent.

    Insensible aux majuscules, au pluriel et à l'ordre : « Armes 1 », « 1 armes », « arme: 1 », « TDC 2 770 »,
    « 2770 cm² », « 1 208 JSN », « JSN 1208 », « 1 208 Jeunes Soldates Naines »...
    """
    rest = " " + text.replace("\n", " ; ") + " "
    levels = {}
    for word, key in LEVEL_WORDS:                     # niveaux : 1 ou 2 chiffres, nombre plutôt après le mot
        found, rest = take(rest, word, r"\d{1,2}(?!\d)", after_first=True)
        levels[key] = found[0] if found else None
    tdc, rest = take(rest, TDC_WORDS, NUM, after_first=True)
    # unités : « 1 208 JSN » d'habitude ; « JSN 1208 » si le texte commence par un nom d'unité
    unit_first = any(re.match(rf"\s*(?:{w})\b", rest, 0 if case else re.I) for w, _, case in UNIT_WORDS)
    found_army = {}
    for word, unit, case in UNIT_WORDS:
        found, rest = take(rest, word, NUM, after_first=unit_first, case=case, both=False)   # un seul sens : « ces 100 JSN »
        if sum(found):
            found_army[unit] = found_army.get(unit, 0) + sum(found)
    army = {u: found_army[u] for u in UNIT_ORDER if u in found_army} or None    # dans l'ordre du jeu
    return army, levels["armes"], levels["bouclier"], tdc[0] if tdc else None


NO_UNIT = "Aucune unité trouvée. Unités possibles : JSN, SN, NE, JS, S, C, CE, A, AE, SE, Tk, TkE, Tu, TuE."
NO_TDC = "TDC introuvable. Exemple : TDC 2 770"


def parse(text, need_tdc=True):
    """Comme parse_partial, mais l'armée est obligatoire (le TDC aussi si need_tdc) ; Armes et Bouclier absents = 0."""
    army, armes, bouclier, tdc = parse_partial(text)
    if not army:
        raise ParseError(NO_UNIT)
    if tdc is None and need_tdc:
        raise ParseError(NO_TDC)
    return army, armes or 0, bouclier or 0, tdc


def counts(text):
    """(VC, nombre de chasses, texte sans eux) ; None pour ce qui manque. La VC est lue avant « chasses » (« vitesse de
    chasse 2 » n'est pas « 2 chasses »)."""
    rest = " " + text.replace("\n", " ; ") + " "
    vc, rest = take(rest, VC_WORDS, r"\d{1,2}(?!\d)", after_first=True)
    hunts, rest = take(rest, HUNTS_WORDS, r"\d{1,2}(?!\d)", after_first=False)
    return vc[0] if vc else None, hunts[0] if hunts else None, rest


def va_of(text):
    """(VA, texte sans elle) ; None si absente. Seulement « va 5 » (mot puis nombre) : « va » est aussi un mot courant."""
    va, rest = take(" " + text.replace("\n", " ; ") + " ", VA_WORDS, r"\d{1,2}(?!\d)", after_first=True, both=False)
    return va[0] if va else None, rest


def army_only(text):
    """Armée seule, sans Armes, Bouclier, TDC, perte ni réplique -> {unité: n} ; None sinon."""
    if re.search(REPLIQUE_WORDS, text, re.I):
        return None
    rest = " " + text.replace("\n", " ; ") + " "
    if va_of(text)[0] is not None:
        return None
    for word in [VC_WORDS, HUNTS_WORDS] + [w for w, _ in LEVEL_WORDS] + [TDC_WORDS, PERTE_WORDS]:
        found, rest = take(rest, word, NUM, after_first=True)
        if found:
            return None
    try:
        return parse(text, need_tdc=False)[0]
    except ParseError:
        return None


_STATS = {}


def split_army(army, tdc, size, hunts):
    """Armée répartie entre `hunts` chasses simultanées de `size` cm², comme le simulateur Calystène : la chasse n° k
    part d'un TDC = tdc + k × size (les chasses en cours comptent) et reçoit une part de chaque unité proportionnelle
    à sa difficulté. On répartit de la dernière à la première ; la première prend le reste."""
    diff = [hunt_mc.food_target(tdc + k * size, size) for k in range(hunts)]
    left, parts = dict(army), [None] * hunts
    for k in reversed(range(hunts)):
        share = diff[k] / sum(diff[:k + 1])
        parts[k] = {u: left[u] if k == 0 else round(left[u] * share) for u in left}
        left = {u: left[u] - parts[k][u] for u in left}
    return [{u: c for u, c in p.items() if c} for p in parts]


def stats(army, tdc, size, armes, bouclier, n, seed=1, rep=10, hunts=1):
    """(risque de réplique > rep % en %, pertes moyennes, pire cas, {pertes: nb de fois}, {unité: pertes} du pire
    combat) sur n tirages, mis en cache.

    Mêmes tirages pour toutes les tailles et tous les TDC (graine fixe) : les courbes sont lisses, les recherches
    dichotomiques ne sautent plus d'une taille à l'autre à cause du hasard.

    hunts > 1 : `hunts` chasses simultanées de `size` cm² chacune (armée répartie par split_army, tirages différents
    par chasse). Risque = au moins une chasse au-dessus de la réplique ; pertes moyennes et pire cas additionnés (le
    pire cas est donc un majorant) ; pas de détail des pertes (None, None)."""
    if hunts > 1:
        parts = split_army(army, tdc, size, hunts)
        if not all(parts):                                      # pas assez d'unités pour toutes les chasses
            return 100.0, float(sum(army.values())), sum(army.values()), None, None
        res = [stats(p, tdc + k * size, size, armes, bouclier, n, seed + k, rep) for k, p in enumerate(parts)]
        safe = math.prod(1 - r[0] / 100 for r in res)
        return 100 * (1 - safe), sum(r[1] for r in res), sum(r[2] for r in res), None, None
    key = (tuple(army.items()), tdc, size, armes, bouclier, n, seed)
    if key not in _STATS:
        if len(_STATS) > 20000:
            _STATS.clear()
        _STATS[key] = _stats(army, tdc, size, armes, bouclier, n, seed)
    risks, mean, worst, losses, worst_units = _STATS[key]
    return risks[rep], mean, worst, losses, worst_units


PICKS_KEPT = 24                                      # tirages (type, %) gardés par meute ; la suite est tirée à la demande
_PICKS = {}


def _more_picks(seed, i):
    rng = random.Random((seed * 1_000_003 + i) * 7 + 1)
    while True:
        yield rng.randrange(len(hunt_mc.PREY)), 45 + rng.randrange(31)


def _picks(seed, i):
    """Les tirages de la meute n° i, préparés une fois : les mêmes pour toutes les tailles et tous les TDC."""
    if (seed, i) not in _PICKS:
        rng = random.Random(seed * 1_000_003 + i)
        _PICKS[seed, i] = [(rng.randrange(len(hunt_mc.PREY)), 45 + rng.randrange(31)) for _ in range(PICKS_KEPT)]
    return itertools.chain(_PICKS[seed, i], _more_picks(seed, i))


def _chunk(army, tdc, size, armes, bouclier, seed, first, last):
    """({réplique: nb de fois au-dessus}, {pertes: nb de fois}, {unité: pertes} du 1er pire combat) sur les meutes
    first..last-1."""
    att = sum(hunt_mc.UNITS[u][1] * k for u, k in army.items()) * (1 + 0.1 * armes)
    big, losses, worst_units = dict.fromkeys(REPLIQUES, 0), Counter(), {}
    for i in range(first, last):
        prey = hunt_mc.draw_prey_from(tdc, size, _picks(seed, i))
        life = sum(k * hunt_mc.PREY[j][2] for j, k in enumerate(prey))
        for rep, mult in REPLIQUES.items():
            big[rep] += att <= mult * life
        units = {u: k for u, k in hunt_mc.fight_losses(army, prey, armes, bouclier).items() if k}
        losses[sum(units.values())] += 1
        if sum(units.values()) > sum(worst_units.values()):           # strict : le 1er pire, comme sur un seul cœur
            worst_units = units
    return big, losses, worst_units


_POOL = None


def _pool():
    """Un processus par cœur (4 sur le Pi), créé une fois. None si impossible : calcul sur un seul cœur."""
    global _POOL
    if _POOL is None:
        try:
            _POOL = ProcessPoolExecutor(os.cpu_count() or 1) if (os.cpu_count() or 1) > 1 else False
        except (OSError, NotImplementedError):
            _POOL = False
    return _POOL or None


def _stats(army, tdc, size, armes, bouclier, n, seed):
    args = (army, tdc, size, armes, bouclier, seed)
    parts = None
    if _pool() and n >= 500:
        cuts = [n * k // _POOL._max_workers for k in range(_POOL._max_workers + 1)]
        try:
            parts = list(_POOL.map(_chunk, *zip(*[args + (a, b) for a, b in zip(cuts, cuts[1:])])))
        except Exception:                                         # processus cassé : on continue sur un seul cœur
            logging.exception("calcul en parallèle impossible, retour sur un seul cœur")
            parts = None
    if parts is None:
        parts = [_chunk(*args, 0, n)]
    risks = {rep: 100 * sum(p[0][rep] for p in parts) / n for rep in REPLIQUES}
    losses = sum((p[1] for p in parts), Counter())
    worst_units = max((p[2] for p in parts), key=lambda w: sum(w.values()))   # max garde le 1er à égalité
    return risks, sum(k * c for k, c in losses.items()) / n, max(losses), losses, worst_units


def buckets(losses, cap, parts=BUCKETS):
    """[(de, à, % des chasses, nb de chasses)] : parts tranches égales de 0 à cap pertes. Les % font 100 tout pile (au 0,1 près,
    reste réparti sur les plus gros arrondis perdus)."""
    edges = [round(cap * i / parts) for i in range(parts + 1)]
    ranges = [(0 if i == 0 else edges[i] + 1, edges[i + 1]) for i in range(parts)]
    ranges = [(a, b) for a, b in ranges if a <= b]
    ranges[-1] = (ranges[-1][0], max(ranges[-1][1], max(losses)))     # rien ne doit dépasser la dernière tranche
    n = sum(losses.values())
    counts = [sum(c for k, c in losses.items() if a <= k <= b) for a, b in ranges]
    exact = [1000 * c / n for c in counts]
    tenths = [int(x) for x in exact]
    for i in sorted(range(len(exact)), key=lambda i: tenths[i] - exact[i])[:1000 - sum(tenths)]:
        tenths[i] += 1
    return [(a, b, t / 10, c) for (a, b), t, c in zip(ranges, tenths, counts)]


def largest_size(risk, target, hi):
    """Plus grande taille dont le risque est ≤ target (le risque monte avec la taille : recherche dichotomique)."""
    lo = 0
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if risk(mid) <= target:
            lo = mid
        else:
            hi = mid - 1
    return lo


def upper_size(ok):
    """Première taille (8, 16, 32…) où ok devient faux : borne haute de la recherche dichotomique. Pas de plafond :
    une chasse assez grosse finit toujours perdue."""
    hi = 8
    while ok(hi):
        hi *= 2
    return hi


def sizes(army, tdc, armes, bouclier, n=5000, rep=10, hunts=1):
    """Tailles de chasse pour chaque niveau de risque de TARGETS (sans doublon, croissantes)."""
    risk = lambda size: stats(army, tdc, size, armes, bouclier, n, rep=rep, hunts=hunts)[0]
    found = [largest_size(risk, t, upper_size(lambda s: risk(s) <= TARGETS[-1])) for t in TARGETS]
    return sorted({s for s in found if s > 0})


def fmt_n(n):
    return f"{n:,}".replace(",", " ")


def fmt_pct(p):
    p = round(p * 2) / 2 if p < 10 else round(p)       # 7,5 % ; 12 %
    return f"{p:g} %".replace(".", ",")


SHORT = {"jsn": "JSN", "sn": "SN", "ne": "NE", "js": "JS", "s": "S", "c": "C", "ce": "CE", "a": "A", "ae": "AE",
         "se": "SE", "tk": "Tk", "tke": "TkE", "tu": "Tu", "tue": "TuE"}


def army_text(army):
    return " + ".join(f"{fmt_n(k)} {SHORT[u]}" for u, k in army.items())


def comma(x):
    return f"{x:.1f}".replace(".", ",")


def star_sizes(army, tdc, armes, bouclier, rows, n=5000, hunts=1):         # même n que le tableau : chiffres identiques
    """{taille: symbole} : pour chaque seuil de STARS, la plus grosse chasse qui garde ce % du meilleur cm²/perte.

    Le rendement ne baisse pas régulièrement : il remonte par endroits (paliers de réplique 10/30/50 %). On balaie donc
    les tailles au-delà du meilleur (même au-delà de 20 % de risque) jusqu'à ce qu'il reste sous le seuil le plus bas
    sur 20 % de taille, puis on affine au cm² près. Une chasse dont le pire cas tue toute l'armée est perdue : son
    cm²/perte ne veut plus rien dire (il monte avec la taille), le balayage s'arrête avant."""
    best_size, best = max(((r[0], r[4]) for r in rows), key=lambda x: x[1])
    total = sum(army.values())

    def per_loss(s):
        _, mean, worst, *_ = stats(army, tdc, s, armes, bouclier, n, hunts=hunts)
        return 0 if worst >= total else s * hunts / mean if mean else float("inf")
    limits = [keep * best for keep, _ in STARS]
    step = max(1, best_size // 40)
    last = [best_size] * len(STARS)                   # plus grosse taille vue au-dessus de chaque seuil
    s = best_size
    while s - max(last) < max(5 * step, 0.2 * s):
        s += step
        ratio = per_loss(s)
        last = [s if ratio >= lim else l for lim, l in zip(limits, last)]
    for k, lim in enumerate(limits):                  # au cm² près, juste après la dernière taille retenue
        last[k] = max([last[k]] + [t for t in range(last[k] + 1, last[k] + step) if per_loss(t) >= lim])
    marks = {}
    for size, (_, symbol) in zip(last, STARS):
        marks.setdefault(size, symbol)                # même taille pour les deux : on garde ⭐
    return marks


def best_ratio_size(marks, ratio):
    """Taille au meilleur cm²/perte, entre la 1re et la dernière taille repère (marks, croissantes) : balayage puis
    affinage au cm² près. À égalité, la plus grosse chasse."""
    key = lambda s: (ratio(s), s)
    lo, hi = marks[0], marks[-1]
    step = max(1, (hi - lo) // 25)
    best = max(list(marks) + list(range(lo, hi + 1, step)), key=key)
    return max(range(max(lo, best - step + 1), min(hi, best + step - 1) + 1), key=key)


def key_rows(army, armes, bouclier, tdc, n=5000, rep=10, hunts=1):
    """Les lignes utiles [(taille, risque, pertes moy., pire cas, cm²/perte, symboles)] : 🛡 plus grosse chasse à
    1 % de risque, 📈 meilleur cm²/perte, ⭐ opti, 🔥 flemme. Une taille qui a plusieurs rôles cumule les symboles.
    Le risque est celui de dépasser la réplique rep % : avec 30, les lignes étudiées sont plus grosses. 📈 ne dépend
    pas de rep (repères à 10 %) ; ⭐ et 🔥 se comparent au meilleur cm²/perte des lignes de rep."""
    def row(s):
        risk, mean, worst, *_ = stats(army, tdc, s, armes, bouclier, n, rep=rep, hunts=hunts)
        return s, risk, mean, worst, s * hunts / mean if mean else float("inf")             # cm² par JSN perdue
    rows = [row(s) for s in sizes(army, tdc, armes, bouclier, n, rep, hunts)]
    if not rows:
        return []
    base = [r[0] for r in rows] if rep == 10 else sizes(army, tdc, armes, bouclier, n, 10, hunts) or [r[0] for r in rows]
    top = best_ratio_size(base, lambda s: row(s)[4])
    if rep == 10 and top not in [r[0] for r in rows]:
        rows = sorted(rows + [row(top)])
    marks = star_sizes(army, tdc, armes, bouclier, rows, n, hunts)
    roles = {}
    for s, symbol in [(rows[0][0], "🛡"), (top, "📈")] + [(s, m) for s, m in marks.items()]:
        roles[s] = roles.get(s, "") + symbol
    if "🔥" not in "".join(roles.values()):                                 # 🔥 sur la même taille que ⭐
        roles[next(s for s, m in marks.items() if m == "⭐")] += "🔥"
    return [row(s) + (roles[s],) for s in sorted(roles)]


def fdf(army, armes):
    """Force de frappe : attaque totale de l'armée avec le bonus d'Armes (+10 % par niveau)."""
    return round(sum(hunt_mc.UNITS[u][1] * k for u, k in army.items()) * (1 + 0.1 * armes))


def best_hunts(army, armes, bouclier, tdc, max_hunts, rep=10, n=CHOICE_DRAWS):
    """Nombre de chasses simultanées, comme le mode auto de Calystène : le plus grand nombre (≤ max_hunts) dont la
    chasse ⭐ fait au moins MIN_HUNT_SHARE % du TDC ; 1 sinon."""
    floor = round(tdc * MIN_HUNT_SHARE / 100)
    for hunts in range(max_hunts, 1, -1):
        rows = key_rows(army, armes, bouclier, tdc, n, rep, hunts)
        if next((r[0] for r in rows if "⭐" in r[5]), 0) >= floor:
            return hunts
    return 1


def table(army, armes, bouclier, tdc, n=5000, rep=10, hunts=1):
    """Le message prêt à coller sur Discord (avec les ```), étroit pour le téléphone : les lignes utiles.

    hunts > 1 : tailles par chasse (« 3×120 cm² »), risque = au moins une chasse, pertes = total des chasses, puis la
    répartition de l'armée pour la taille ⭐."""
    rows = key_rows(army, armes, bouclier, tdc, n, rep, hunts)
    if not rows:
        return "```\n🎯 Aucune chasse possible : armée trop faible pour ce TDC.\n```"
    multi = f"{hunts}×" if hunts > 1 else ""
    lines = ["```", "🎯 Chasses conseillées" + (f" : {hunts} chasses en même temps" if hunts > 1 else "")
             + (f" (réplique {rep} %)" if rep != 10 else ""),
             f"   ({army_text(army)}, Armes {armes}, Bouclier {bouclier}, TDC {fmt_n(tdc)})",
             f"   (FDF : {fmt_n(fdf(army, armes))})", ""]
    if hunts > 1:
        lines[-1:-1] = [f"   (risque : au moins 1 chasse ; pertes : total des {hunts})"]
    width = max(7, max(len(f"{multi}{r[0]} cm²") for r in rows))
    lines += [f" {'Chasse':<{width}} | Réplique > {rep} % | Pertes moy. | cm²/perte | Pire cas",
              "-" * (width + 2) + "+-----------------+-------------+-----------+---------"]
    for s, risk, mean, worst, per_loss, roles in rows:
        lines.append(f" {f'{multi}{s} cm²':<{width}} | {fmt_pct(risk):<15} | {comma(mean):<11} | "
                     f"{comma(per_loss) if mean else 'sans perte':<9} | {str(worst):<8} {roles}")
    lines += ["🛡 min. pertes  📈 meilleur cm²/perte",
              f"⭐ opti ({round(STARS[0][0] * 100)} % du meilleur{f' en réplique {rep} %' if rep != 10 else ''})  "
              f"🔥 flemme ({round(STARS[1][0] * 100)} %)"]
    if hunts > 1:
        star = next(r[0] for r in rows if "⭐" in r[5])
        lines += ["", f"⭐ Répartition pour {hunts}×{star} cm² (dans l'ordre de lancement) :"]
        lines += [f" {k + 1}. {army_text(part)}" for k, part in enumerate(split_army(army, tdc, star, hunts))]
    return "\n".join(lines + ["```"])


def max_loss_size(army, armes, bouclier, tdc, cap, n=5000):
    """Plus grosse chasse dont le pire cas reste ≤ cap pertes (0 si aucune).

    Le pire cas monte avec la taille mais pas régulièrement (194 cm² : 102, 196 cm² : 101) : après la recherche
    dichotomique, on balaie au cm² près jusqu'à 5 % au-delà de la dernière taille retenue."""
    worst = lambda s: stats(army, tdc, s, armes, bouclier, n)[2]
    best = largest_size(worst, cap, upper_size(lambda s: worst(s) <= cap))
    s = best
    while s - best < max(5, best // 20):
        s += 1
        if worst(s) <= cap:
            best = s
    return best


def loss_table(army, armes, bouclier, tdc, cap, n=5000):
    """Une seule ligne : la plus grosse chasse avec au pire cap pertes. Sans réplique."""
    cap = min(cap, sum(army.values()) - 1)            # toute l'armée perdue = chasse perdue : jamais proposée
    head = [f"🎯 Chasse pour {fmt_n(cap)} pertes max",
            f"   ({army_text(army)}, Armes {armes}, Bouclier {bouclier}, TDC {fmt_n(tdc)})", ""]
    size = max_loss_size(army, armes, bouclier, tdc, cap, n)
    if not size:
        return "\n".join(["```"] + head + [f"Aucune chasse possible avec au pire {fmt_n(cap)} pertes.", "```"])
    _, mean, worst, losses, lost = stats(army, tdc, size, armes, bouclier, n)
    detail = [f"Pire cas : {army_text(lost)}"] if len(lost) > 1 else []     # plusieurs types d'unités touchés
    return "\n".join(["```"] + head + [
        " Chasse   | Pertes moy. | cm²/perte | Pire cas",
        "----------+-------------+-----------+---------",
        f" {f'{size} cm²':<8} | {comma(mean):<11} | {comma(size / mean) if mean else 'sans perte':<9} | {worst}",
        ] + detail + ["", "📊 Chances selon les pertes :"]
        + [f" {f'{fmt_n(a)} à {fmt_n(b)} pertes':<17} : {fmt_pct1(p) if p or not c else '< 0,1 %'}"
           for a, b, p, c in buckets(losses, cap)] + ["```"])


def fmt_pct1(p):
    return f"{p:.1f}".replace(".0", "").replace(".", ",") + " %"


def perte(text):
    """(pertes max demandées ou None, texte sans « perte XXX »)."""
    found, rest = take(" " + text + " ", PERTE_WORDS, NUM, after_first=True)
    return (found[-1], rest) if found else (None, text)


ENORME_TEUB = r"""```
     ____
    /    \
   (   |  )
    \____/
    |    |
    |    |
    |    |
    |    |
    |    |
  __|    |__
 /   \  /   \
(     )(     )
 \___/  \___/
```"""


def read(text):
    """{"rep", "cap", "vc", "va", "hunts", "army", "armes", "bouclier", "tdc"} du message ; None pour ce qui manque
    (rep vaut 10 par défaut)."""
    rep, text = replique(text)
    cap, text = perte(text)
    vc, hunts, text = counts(text)
    va, text = va_of(text)
    army, armes, bouclier, tdc = parse_partial(text)
    return {"rep": rep, "cap": cap, "vc": vc, "va": va, "hunts": hunts, "army": army, "armes": armes,
            "bouclier": bouclier, "tdc": tdc}


def answer(text, fiche=None):
    """Réponse du bot à un texte collé (tableau, ou message d'erreur).

    Ce qui manque dans le message (armée, Armes, Bouclier, VC) est pris dans la fiche du joueur {"armee",
    "armee_maj", "armes", "bouclier", "vc"} ; ce qui est dans le message passe avant la fiche. Nombre de chasses :
    « 3 chasses » dans le message, sinon VC + 1, sinon 1."""
    if re.search(r"[ée]norme\s+teub", text, re.IGNORECASE):     # easter egg
        return ENORME_TEUB
    fiche = fiche or {}
    try:
        found = read(text)
        rep, cap, army, armes, bouclier, tdc = (found[k] for k in ("rep", "cap", "army", "armes", "bouclier", "tdc"))
        from_fiche = []
        if not army and fiche.get("armee"):
            army = fiche["armee"]
            from_fiche.append(f"armée du {fiche['armee_maj']}" if fiche.get("armee_maj") else "armée")
        for name, value in (("Armes", armes), ("Bouclier", bouclier)):
            if value is None and fiche.get(name.lower()) is not None:
                from_fiche.append(name)
        armes = fiche.get("armes") or 0 if armes is None else armes
        bouclier = fiche.get("bouclier") or 0 if bouclier is None else bouclier
        vc = found["vc"]
        if vc is None and found["hunts"] is None and fiche.get("vc") is not None:
            vc = fiche["vc"]
            from_fiche.append("VC")
        hunts = found["hunts"]                           # « 3 chasses » : imposé ; sinon choisi selon la VC, plus bas
        if not 1 <= (hunts or (vc or 0) + 1) <= MAX_HUNTS:
            raise ParseError(f"Nombre de chasses entre 1 et {MAX_HUNTS}.")
        if not army:
            raise ParseError(NO_UNIT + "\nOu enregistre ton armée dans le salon profil, puis écris juste `TDC 2 770`.")
        if tdc is None:
            raise ParseError(NO_TDC)
    except ParseError as e:
        if "TDC" in str(e) and re.search(r"\d\s*pertes?\b", text, re.I):     # « TDC 2 770 100 pertes » : nombres collés
            e = f"{e}\nSi « pertes » suit le TDC, mets une virgule avant ou écris `perte 100`."
        return f"❌ {e}\nExemple : `1 208 JSN + 99 SN, Armes 1, Bouclier 2, TDC 2 770` (+ `réplique 30` ou `perte 100` si besoin)"
    note = f"📋 Pris dans ta fiche : {', '.join(from_fiche)}\n" if from_fiche else ""
    if cap is not None:                                  # « perte XXX » : une seule chasse
        if (hunts or 1) > 1:
            note += "ℹ️ `perte` : calcul pour 1 seule chasse.\n"
        return note + loss_table(army, armes, bouclier, tdc, cap)
    if hunts is None:
        hunts = best_hunts(army, armes, bouclier, tdc, vc + 1, rep) if vc else 1
        floor = fmt_n(round(tdc * MIN_HUNT_SHARE / 100))
        if vc and hunts == 1:
            note += (f"🔀 1 seule chasse (VC {vc} : jusqu'à {vc + 1} possibles). À 2 chasses ou plus, chaque chasse "
                     f"ferait moins de {MIN_HUNT_SHARE} % de ton TDC ({floor} cm²) : pas rentable.\n")
        elif vc:
            note += (f"🔀 {hunts} chasses en même temps (VC {vc} : jusqu'à {vc + 1} possibles), chacune d'au moins "
                     f"{MIN_HUNT_SHARE} % de ton TDC ({floor} cm²). `1 chasse` pour une seule.\n")
    return note + table(army, armes, bouclier, tdc, rep=rep, hunts=hunts)


def replique(text):
    """(réplique comptée, texte sans « réplique XX ») ; 10 par défaut."""
    found = re.findall(REPLIQUE_WORDS, text, re.IGNORECASE)
    if not found:
        return 10, text
    rep = int(found[-1])
    if rep not in REPLIQUES:
        raise ParseError(f"Réplique {rep} % impossible. Valeurs possibles : {', '.join(map(str, REPLIQUES))}.")
    return rep, re.sub(REPLIQUE_WORDS, " ; ", text, flags=re.IGNORECASE)


if __name__ == "__main__":                           # essai en local : python bot_chasse/risque.py "1 208 JSN ..."
    sys.stdout.reconfigure(encoding="utf-8")
    print(answer(" ".join(sys.argv[1:]) or "1 208 JSN + 99 SN, Armes 1, Bouclier 2, TDC 2 770"))
