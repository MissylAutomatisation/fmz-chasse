"""Niveaux rentables d'Armes et de Bouclier : « /niveau 989 JSN + 252 SN + 240 JS » -> tableau par unité pondue.

Armes et Bouclier coûtent 80 × 2^N ouvrières pour passer de N à N+1, soit 80 × 2^N × 60 s de ponte. On compare :
- Armes : +10 % de la FDF de base de l'armée, contre la FDF qu'aurait donnée la même durée de ponte de chaque unité
  (ou du mélange de l'armée), au bonus du niveau N ;
- Bouclier : vie gagnée (arrondie par unité : base + arrondi(base × niveau / 10), comme toolzzz), contre la vie
  de la même durée de ponte de JSN au Bouclier N (le tampon des pertes).
Armée figée : les pontes futures ne comptent pas. Le TDP accélère ouvrières et unités pareil : il s'annule. Les 🍎
et 🪵 ne comptent pas (le coût limitant, ce sont les ouvrières).
"""
import re

import risque

COMMAND = r"^\s*/?niveaux?\b"                        # « /niveau … » ou « niveau … » en début de message
OV_COST = 80                                         # ouvrières d'Armes 1 et de Bouclier 1, × 2 à chaque niveau
OV_PONTE = 60                                        # ponte d'une ouvrière (s, base)
PONTE = {"jsn": 300, "sn": 450, "ne": 570, "js": 740, "s": 1000, "c": 1410, "ce": 1410, "a": 1440, "ae": 1520,
         "se": 1450, "tk": 1860, "tke": 1860, "tu": 2740, "tue": 2740}   # ponte de base (s), sheet et toolzzz
COMPARED = ("jsn", "sn", "ne", "js", "s", "a", "tk", "tu")   # unités pondables qui attaquent (pas C, ni élites)
MAX_LEVEL = 60
MAX_JUMP = 3                                         # Bouclier : niveaux pris d'un coup (paliers sans gain d'arrondi)


def is_command(text):
    return re.match(COMMAND, text, re.I) is not None


def base_fdf(army):
    return sum(risque.hunt_mc.UNITS[u][1] * k for u, k in army.items())


def base_life(army):
    return sum(risque.hunt_mc.UNITS[u][0] * k for u, k in army.items())


def per_second(total, laid):
    """Stat de base par seconde de ponte de l'armée laid ({unité: nombre})."""
    return total(laid) / sum(PONTE[u] * k for u, k in laid.items())


def ratio(gain, rate, level):
    """Gain du niveau level (depuis level − 1) divisé par la stat que donnerait la ponte de ses ouvrières."""
    n = level - 1
    return gain / (OV_COST * 2 ** n * OV_PONTE * rate * (1 + n / 10))


def best_level(gain, rate):
    """(niveau max rentable, ratio du niveau suivant). Le ratio est divisé par ~2 à chaque niveau."""
    level = 0
    while level < MAX_LEVEL and ratio(gain, rate, level + 1) >= 1:
        level += 1
    return level, ratio(gain, rate, level + 1)


def armes_rows(army):
    """[(nom, niveau max, ratio du suivant)] : l'armée (même mélange) puis chaque unité de COMPARED."""
    gain = base_fdf(army) * 0.1
    laids = [("Armée", army)] + [(risque.SHORT[u], {u: 1}) for u in COMPARED]
    return [(name, *best_level(gain, per_second(base_fdf, laid))) for name, laid in laids]


def life(unit, level):
    """Vie d'une unité au Bouclier level : base + arrondi(base × level / 10), 0,5 vers le haut."""
    base = risque.hunt_mc.UNITS[unit][0]
    return base + (base * level + 5) // 10


def bouclier_ratio(army, start, end):
    """Vie gagnée de start à end, divisée par la vie des JSN pondues avec les ouvrières de chaque niveau."""
    gain = sum(k * (life(u, end) - life(u, start)) for u, k in army.items())
    ponte = sum(OV_COST * 2 ** n * OV_PONTE / PONTE["jsn"] * life("jsn", n) for n in range(start, end))
    return gain / ponte


def bouclier_level(army):
    """(niveau max rentable, ratio du niveau suivant). Un niveau sans gain (arrondi) est pris avec les suivants
    s'ils sont rentables ensemble (jusqu'à MAX_JUMP d'un coup)."""
    level = 0
    while level < MAX_LEVEL:
        jump = next((j for j in range(1, MAX_JUMP + 1) if bouclier_ratio(army, level, level + j) >= 1), None)
        if jump is None:
            break
        level += jump
    return level, max(bouclier_ratio(army, level, level + j) for j in range(1, MAX_JUMP + 1))


def pct(r):
    return f"{round(r * 100)} %"


def answer(text):
    try:
        army, armes, bouclier, _ = risque.parse(re.sub(COMMAND, " ", text, flags=re.I), need_tdc=False)
    except risque.ParseError as e:
        return f"❌ {e}\nExemple : `/niveau 989 JSN + 252 SN + 240 JS`"
    fmt = risque.fmt_n
    now = lambda lvl: f" (tu es à {lvl})" if lvl else ""
    lines = ["```", "⚔️ Niveaux rentables", f"   ({risque.army_text(army)})", "",
             f"Armes : FDF de base {fmt(base_fdf(army))}{now(armes)}",
             " Si tu ponds | Max rentable | Niveau suivant",
             "-------------+--------------+---------------"]
    for name, lvl, nxt in armes_rows(army):
        lines.append(f" {name:<11} | Armes {lvl:<6} | {pct(nxt)}")
    lvl, nxt = bouclier_level(army)
    lines += ["", f"Bouclier : vie de base {fmt(base_life(army))}{now(bouclier)}",
              f" Comparé à la ponte de JSN : Bouclier {lvl} max (suivant : {pct(nxt)})", "",
              "Niveau suivant = ce qu'il rapporte par rapport",
              "à la ponte qu'il coûte (60 s par OV). 100 % = égal."]
    return "\n".join(lines + ["```"])
