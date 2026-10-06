"""Risque selon la taille de chasse : lit « 1 208 JSN + 99 SN, Armes 1, Bouclier 2, TDC 2 770 » et rend le tableau.

Moteur : hunt_mc.py (tirages de prédateurs réalistes, repris de fourmizzz-zero-perte.pages.dev).
« Réplique > 10 % » = au 1er tour, l'attaque ne dépasse pas 3 fois la vie des prédateurs (> 30 % : 2 fois, > 50 % :
1,5 fois). Par défaut 10 % ; « réplique 30 » ou « réplique 50 » dans le message change le seuil compté.
"""
import itertools
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
LEVEL_WORDS = [(r"bouc[^\W\d_]*(?:\s+thoraciques?)?", "bouclier"), (r"arm[^\W\d_]*", "armes")]   # lettres seules : « armes1 »
TDC_WORDS = r"tdc|terrains?(?:\s+de\s+chasse)?|cm²|cm2|cm"
TARGETS = (1, 2, 5, 7.5, 10, 15, 20)                          # niveaux de risque (%) des tailles repères
MAX_SIZE = 5000
STARS = ((0.85, "⭐"), (0.80, "🔥"))               # plus grosse chasse qui garde 85 % / 80 % du meilleur cm²/perte
BUCKETS = 4                                          # tranches égales de 0 à la limite, sous « perte XXX »
NEXT_HUNTS = 5                                       # chasses ⭐ prévues à la suite, pire cas de pertes retiré à chaque fois
REPLIQUES = {10: 3, 30: 2, 50: 1.5}                  # réplique comptée (%) -> l'attaque doit dépasser ce multiple de la vie
REPLIQUE_WORDS = r"r[ée]pli(?:que)?s?\s*[:=]?\s*(\d+)\s*%?"   # « réplique 30 », « Replique: 50 % », « répli 30 »
PERTE_WORDS = r"pertes?(?:\s+max(?:imum|imales?|i)?)?"      # « perte 100 », « pertes max 100 », « 100 pertes »


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


def parse(text, need_tdc=True):
    """Texte libre -> (armée {"jsn": n, "sn": n, "js": n}, armes, bouclier, tdc ; None si absent et need_tdc=False).

    Insensible aux majuscules, au pluriel et à l'ordre : « Armes 1 », « 1 armes », « arme: 1 », « TDC 2 770 »,
    « 2770 cm² », « 1 208 JSN », « JSN 1208 », « 1 208 Jeunes Soldates Naines »...
    """
    rest = " " + text.replace("\n", " ; ") + " "
    levels = {}
    for word, key in LEVEL_WORDS:                     # niveaux : 1 ou 2 chiffres, nombre plutôt après le mot
        found, rest = take(rest, word, r"\d{1,2}", after_first=True)
        levels[key] = found[0] if found else 0
    tdc, rest = take(rest, TDC_WORDS, NUM, after_first=True)
    # unités : « 1 208 JSN » d'habitude ; « JSN 1208 » si le texte commence par un nom d'unité
    unit_first = any(re.match(rf"\s*(?:{w})\b", rest, 0 if case else re.I) for w, _, case in UNIT_WORDS)
    found_army = {}
    for word, unit, case in UNIT_WORDS:
        found, rest = take(rest, word, NUM, after_first=unit_first, case=case, both=False)   # un seul sens : « ces 100 JSN »
        if sum(found):
            found_army[unit] = found_army.get(unit, 0) + sum(found)
    army = {u: found_army[u] for u in UNIT_ORDER if u in found_army}         # dans l'ordre du jeu
    if not army:
        raise ParseError("Aucune unité trouvée. Unités possibles : JSN, SN, NE, JS, S, C, CE, A, AE, SE, Tk, TkE, Tu, TuE.")
    if not tdc and need_tdc:
        raise ParseError("TDC introuvable. Exemple : TDC 2 770")
    return army, levels["armes"], levels["bouclier"], tdc[0] if tdc else None


_STATS = {}


def stats(army, tdc, size, armes, bouclier, n, seed=1, rep=10):
    """(risque de réplique > rep % en %, pertes moyennes, pire cas, {pertes: nb de fois}, {unité: pertes} du pire
    combat) sur n tirages, mis en cache.

    Mêmes tirages pour toutes les tailles et tous les TDC (graine fixe) : les courbes sont lisses, les recherches
    dichotomiques ne sautent plus d'une taille à l'autre à cause du hasard."""
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


def sizes(army, tdc, armes, bouclier, n=5000, rep=10):
    """Tailles de chasse pour chaque niveau de risque de TARGETS (sans doublon, croissantes)."""
    risk = lambda size: stats(army, tdc, size, armes, bouclier, n, rep=rep)[0]
    hi = 8
    while hi < MAX_SIZE and risk(hi) <= TARGETS[-1]:
        hi *= 2
    found = [largest_size(risk, t, min(hi, MAX_SIZE)) for t in TARGETS]
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


def star_sizes(army, tdc, armes, bouclier, rows, n=5000):         # même n que le tableau : chiffres identiques
    """{taille: symbole} : pour chaque seuil de STARS, la plus grosse chasse qui garde ce % du meilleur cm²/perte.

    Le rendement ne baisse pas régulièrement : il remonte par endroits (paliers de réplique 10/30/50 %). On balaie donc
    les tailles au-delà du meilleur (même au-delà de 20 % de risque) jusqu'à ce qu'il reste sous le seuil le plus bas
    sur 20 % de taille, puis on affine au cm² près."""
    best_size, best = max(((r[0], r[4]) for r in rows), key=lambda x: x[1])
    per_loss = lambda s: (lambda m: s / m if m else float("inf"))(stats(army, tdc, s, armes, bouclier, n)[1])
    limits = [keep * best for keep, _ in STARS]
    step = max(1, best_size // 40)
    last = [best_size] * len(STARS)                   # plus grosse taille vue au-dessus de chaque seuil
    s = best_size
    while s + step <= MAX_SIZE and s - max(last) < max(5 * step, 0.2 * s):
        s += step
        ratio = per_loss(s)
        last = [s if ratio >= lim else l for lim, l in zip(limits, last)]
    for k, lim in enumerate(limits):                  # au cm² près, juste après la dernière taille retenue
        last[k] = max([last[k]] + [t for t in range(last[k] + 1, min(last[k] + step, MAX_SIZE + 1)) if per_loss(t) >= lim])
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


def key_rows(army, armes, bouclier, tdc, n=5000, rep=10):
    """Les lignes utiles [(taille, risque, pertes moy., pire cas, cm²/perte, symboles)] : 🛡 plus grosse chasse à
    1 % de risque, 📈 meilleur cm²/perte, ⭐ opti, 🔥 flemme. Une taille qui a plusieurs rôles cumule les symboles.
    Le risque est celui de dépasser la réplique rep % : avec 30, les lignes étudiées sont plus grosses. 📈 ne dépend
    pas de rep (repères à 10 %) ; ⭐ et 🔥 se comparent au meilleur cm²/perte des lignes de rep."""
    def row(s):
        risk, mean, worst, *_ = stats(army, tdc, s, armes, bouclier, n, rep=rep)
        return s, risk, mean, worst, s / mean if mean else float("inf")             # cm² par JSN perdue
    rows = [row(s) for s in sizes(army, tdc, armes, bouclier, n, rep)]
    if not rows:
        return []
    base = [r[0] for r in rows] if rep == 10 else sizes(army, tdc, armes, bouclier, n, 10) or [r[0] for r in rows]
    top = best_ratio_size(base, lambda s: row(s)[4])
    if rep == 10 and top not in [r[0] for r in rows]:
        rows = sorted(rows + [row(top)])
    marks = star_sizes(army, tdc, armes, bouclier, rows, n)
    roles = {}
    for s, symbol in [(rows[0][0], "🛡"), (top, "📈")] + [(s, m) for s, m in marks.items()]:
        roles[s] = roles.get(s, "") + symbol
    if "🔥" not in "".join(roles.values()):                                 # 🔥 sur la même taille que ⭐
        roles[next(s for s, m in marks.items() if m == "⭐")] += "🔥"
    return [row(s) + (roles[s],) for s in sorted(roles)]


def next_hunts(army, armes, bouclier, tdc, n=5000, rep=10):
    """Les NEXT_HUNTS chasses ⭐ à la suite : [(TDC, taille, pire cas)], puis l'armée et le TDC après.

    Entre deux chasses, le TDC monte de la taille chassée et l'armée perd le pire cas (prudent : une grosse réplique
    sur la 1re chasse pèse aussi sur les suivantes). Les plus faibles meurent d'abord (ordre du jeu)."""
    plan = []
    for _ in range(NEXT_HUNTS):
        rows = key_rows(army, armes, bouclier, tdc, n, rep)
        star = next((r for r in rows if "⭐" in r[5]), None)
        if star is None:
            break
        plan.append((tdc, star[0], star[3]))
        tdc, army = tdc + star[0], lose(army, star[3])
    return plan, army, tdc


def lose(army, k):
    """L'armée après k pertes, les unités les plus faibles d'abord."""
    left = {}
    for u, count in army.items():                                          # army est dans l'ordre du jeu
        dead = min(count, k)
        k -= dead
        if count - dead:
            left[u] = count - dead
    return left


WAIT_PLAN = "📅 Calcul des prochaines chasses ⭐…"


def table(army, armes, bouclier, tdc, n=5000, plan=True, rep=10):
    """Le message prêt à coller sur Discord (avec les ```), étroit pour le téléphone : les lignes utiles et les
    prochaines chasses ⭐ (plan=False : WAIT_PLAN à la place, le bot répond d'abord vite puis complète)."""
    rows = key_rows(army, armes, bouclier, tdc, n, rep)
    if not rows:
        return "```\n🎯 Aucune chasse possible : armée trop faible pour ce TDC.\n```"
    lines = ["```", "🎯 Chasses conseillées" + (f" (réplique {rep} %)" if rep != 10 else ""),
             f"   ({army_text(army)}, Armes {armes}, Bouclier {bouclier}, TDC {fmt_n(tdc)})", "",
             f" Chasse  | Réplique > {rep} % | Pertes moy. | cm²/perte | Pire cas",
             "---------+-----------------+-------------+-----------+---------"]
    for s, risk, mean, worst, per_loss, roles in rows:
        lines.append(f" {f'{s} cm²':<7} | {fmt_pct(risk):<15} | {comma(mean):<11} | "
                     f"{comma(per_loss) if mean else 'sans perte':<9} | {str(worst):<8} {roles}")
    lines += ["🛡 min. pertes  📈 meilleur cm²/perte",
              f"⭐ opti ({round(STARS[0][0] * 100)} % du meilleur{f' en réplique {rep} %' if rep != 10 else ''})  "
              f"🔥 flemme ({round(STARS[1][0] * 100)} %)"]
    if not plan:
        return "\n".join(lines + ["", WAIT_PLAN, "```"])
    plan, army_after, tdc_after = next_hunts(army, armes, bouclier, tdc, n, rep)
    if len(plan) > 1:
        lines += ["", f"📅 {len(plan)} prochaines chasses ⭐ (pire cas retiré à chaque fois)",
                  " #  | TDC     | Chasse  | Pire", "----+---------+---------+-----"]
        lines += [f" {i}  | {fmt_n(t):<7} | {f'{s} cm²':<7} | {w}" for i, (t, s, w) in enumerate(plan, 1)]
        lines.append(f"Après : TDC {fmt_n(tdc_after)}, armée {army_text(army_after) or 'détruite'}")
    return "\n".join(lines + ["```"])


def max_loss_size(army, armes, bouclier, tdc, cap, n=5000):
    """Plus grosse chasse dont le pire cas reste ≤ cap pertes (0 si aucune).

    Le pire cas monte avec la taille mais pas régulièrement (194 cm² : 102, 196 cm² : 101) : après la recherche
    dichotomique, on balaie au cm² près jusqu'à 5 % au-delà de la dernière taille retenue."""
    worst = lambda s: stats(army, tdc, s, armes, bouclier, n)[2]
    best = largest_size(worst, cap, MAX_SIZE)
    s = best
    while s < MAX_SIZE and s - best < max(5, best // 20):
        s += 1
        if worst(s) <= cap:
            best = s
    return best


def loss_table(army, armes, bouclier, tdc, cap, n=5000):
    """Une seule ligne : la plus grosse chasse avec au pire cap pertes. Sans réplique ni prochaines chasses."""
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


def answer(text, plan=True):
    """Réponse du bot à un texte collé (tableau, ou message d'erreur). plan=False : sans les prochaines chasses."""
    if re.search(r"[ée]norme\s+teub", text, re.IGNORECASE):     # easter egg
        return ENORME_TEUB
    raw = text
    try:
        rep, text = replique(text)
        cap, text = perte(text)
        army, armes, bouclier, tdc = parse(text)
    except ParseError as e:
        if "TDC" in str(e) and re.search(r"\d\s*pertes?\b", raw, re.I):     # « TDC 2 770 100 pertes » : nombres collés
            e = f"{e}\nSi « pertes » suit le TDC, mets une virgule avant ou écris `perte 100`."
        return f"❌ {e}\nExemple : `1 208 JSN + 99 SN, Armes 1, Bouclier 2, TDC 2 770` (+ `réplique 30` ou `perte 100` si besoin)"
    if cap is not None:
        return loss_table(army, armes, bouclier, tdc, cap)
    return table(army, armes, bouclier, tdc, plan=plan, rep=rep)


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
