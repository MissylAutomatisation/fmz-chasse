"""Rentabilité d'Armes : « /niveau 989 JSN + 252 SN + 240 JS, Armes 2 » -> vaut-il mieux le niveau suivant ou pondre ?

Instantané, en FDF (force de frappe). Le niveau N -> N+1 donne +10 % de la FDF de base et coûte 80 × 2^N ouvrières.
Ces ouvrières valent 80 × 2^N × 60 s de ponte : on compare avec la FDF qu'aurait donnée la même durée de ponte de
l'armée collée (même mélange d'unités), au bonus d'Armes actuel. Le TDP accélère ouvrières et unités pareil : il
s'annule. Les 🍎 et 🪵 de la recherche ne comptent pas (le coût limitant, ce sont les ouvrières).
"""
import re

import risque

COMMAND = r"^\s*/?niveaux?\b"                        # « /niveau … » ou « niveau … » en début de message
OV_COST = 80                                         # ouvrières d'Armes 1, × 2 à chaque niveau
OV_PONTE = 60                                        # ponte d'une ouvrière (s, base)
PONTE = {"jsn": 300, "sn": 450, "ne": 570, "js": 740, "s": 1000, "c": 1410, "ce": 1410, "a": 1440, "ae": 1520,
         "se": 1450, "tk": 1860, "tke": 1860, "tu": 2740, "tue": 2740}   # ponte de base (s), sheet et toolzzz
SHOWN = 3                                            # niveaux affichés à partir du suivant


def is_command(text):
    return re.match(COMMAND, text, re.I) is not None


def base_fdf(army):
    return sum(risque.hunt_mc.UNITS[u][1] * k for u, k in army.items())


def levels(army, armes, shown=SHOWN):
    """[(niveau visé, coût OV, gain FDF, FDF si on pond à la place, ratio gain / ponte)]."""
    fdf = base_fdf(army)
    fdf_per_s = fdf / sum(PONTE[u] * k for u, k in army.items())      # FDF de base par seconde de ponte
    rows = []
    for n in range(armes, armes + shown):
        ov = OV_COST * 2 ** n
        gain = fdf * 0.1
        ponte = ov * OV_PONTE * fdf_per_s * (1 + n / 10)                # unités pondues au bonus actuel
        rows.append((n + 1, ov, gain, ponte, gain / ponte))
    return rows


def threshold(army, armes):
    """FDF de base à partir de laquelle Armes armes+1 est rentable, à mélange d'unités égal."""
    _, ov, gain, ponte, _ = levels(army, armes, 1)[0]
    return base_fdf(army) * ponte / gain


def answer(text):
    try:
        army, armes, _, _ = risque.parse(re.sub(COMMAND, " ", text, flags=re.I), need_tdc=False)
    except risque.ParseError as e:
        return f"❌ {e}\nExemple : `/niveau 989 JSN + 252 SN + 240 JS, Armes 2`"
    fmt = risque.fmt_n
    lines = ["```", "⚔️ Rentabilité d'Armes (FDF, instantané)",
             f"   ({risque.army_text(army)}, Armes {armes})",
             f"   FDF de base {fmt(base_fdf(army))}, avec Armes {armes} : {fmt(round(base_fdf(army) * (1 + armes / 10)))}", "",
             " Niveau  | Coût OV | Gain FDF | Si ponte | Verdict",
             "---------+---------+----------+----------+---------"]
    for lvl, ov, gain, ponte, ratio in levels(army, armes):
        verdict = f"✅ ×{risque.comma(ratio)}" if ratio >= 1 else f"❌ ×{risque.comma(ratio)}"
        lines.append(f" Armes {lvl:<2}| {fmt(ov):<7} | +{fmt(round(gain)):<7} | +{fmt(round(ponte)):<7} | {verdict}")
    lines += ["", f"Armes {armes + 1} rentable dès {fmt(round(threshold(army, armes)))} de FDF de base.",
              "Si ponte = FDF qu'on aurait en pondant ton armée",
              "pendant le temps des OV dépensées (60 s par OV)."]
    return "\n".join(lines + ["```"])
