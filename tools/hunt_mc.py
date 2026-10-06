"""Chasse réaliste par tirages (Monte-Carlo), repris du moteur de https://fourmizzz-zero-perte.pages.dev/ (2026-10-03).

Même formule de difficulté que sim_start.py, mais les prédateurs sont tirés au hasard comme dans le jeu (chenilles,
guêpes, abeilles...) au lieu de « que des petites araignées ». Ce moteur colle aux RC du S5 (31 cm² à 1 100 TDC :
1,4 perte en moyenne). Sert à proposer des tailles de chasse pour une armée réelle.
"""
import math
import random

# (nom, dégâts, vie) — bestiaire du jeu
PREY = [("Petite araignée", 13, 50), ("Araignée", 19, 75), ("Chenille", 30, 100), ("Criquet", 42, 100),
        ("Guêpe", 50, 140), ("Cigale", 70, 200), ("Abeille", 115, 220), ("Dionée", 70, 700),
        ("Hanneton", 140, 450), ("Scarabée", 230, 1000), ("Mante religieuse", 1200, 800), ("Lézard", 700, 5000),
        ("Souris", 1400, 5000), ("Mulot", 3000, 8000), ("Alouette", 10000, 30000), ("Rat", 50000, 100000),
        ("Tamanoir", 1e6, 5e6)]
# valeur d'un prédateur : racine(vie × dégâts) / 1,1 arrondie à 0,05 ; nourriture = 0,8 × valeur
FOOD = [0.8 * round(20 * math.sqrt(hp * dmg) / 1.1) / 20 for _, dmg, hp in PREY]
# unités (PV, attaque), dans l'ordre où elles encaissent : les plus faibles d'abord
UNITS = {"jsn": (8, 3), "sn": (10, 5), "ne": (13, 7), "js": (16, 10), "s": (20, 15), "c": (30, 1), "ce": (40, 1),
         "a": (10, 30), "ae": (12, 35), "se": (27, 24), "tk": (35, 55), "tke": (50, 80), "tu": (50, 50),
         "tue": (55, 55)}                              # ordre de mort du jeu (toolzzz, class/Combat.js:727-746)


def hunt_factor(tdc):
    return 1.04 ** round(math.log(max(tdc, 50) / 50) / math.log(10 ** 0.1))


def food_target(tdc, amount):
    """Nourriture totale des prédateurs = 0,8 × difficulté de la chasse."""
    return 0.8 * (amount + max(tdc, 50) * 0.01) * hunt_factor(tdc) * 3


def draw_prey(tdc, amount, rng):
    """Tire une meute : tant qu'il reste de la nourriture, un type au hasard prend 45-75 % du total (arrondi bas),
    sinon un paquet de petites araignées valant 5 % du total."""
    return draw_prey_from(tdc, amount, ((rng.randrange(len(PREY)), 45 + rng.randrange(31)) for _ in range(5000)))


def draw_prey_from(tdc, amount, picks):
    """Comme draw_prey, avec les tirages (type, %) donnés : les mêmes tirages resservent pour toutes les tailles."""
    total = food_target(tdc, amount)
    left, counts = total, [0] * len(PREY)
    block = math.ceil(0.05 * total / FOOD[0] - 1e-9)
    picks = iter(picks)
    while left > 1e-9:                                 # tirage pris seulement s'il reste de la nourriture
        kind, pct = next(picks, (None, None))
        if kind is None:
            break
        n = math.floor(min(pct * total / 100, left) / FOOD[kind] + 1e-9)
        if n >= 1:
            counts[kind] += n
            left -= n * FOOD[kind]
        else:
            counts[0] += block
            left -= block * FOOD[0]
    return counts


def fight(army, prey, armes=0, bouclier=0):
    """Combat par tours (PV mis en commun). Renvoie le total des pertes réelles (plus de la moitié des PV = perdue)."""
    return sum(fight_losses(army, prey, armes, bouclier).values())


def fight_losses(army, prey, armes=0, bouclier=0):
    """Comme fight, mais les pertes par type d'unité : {"jsn": 1, ...} (toute l'armée si la chasse est perdue)."""
    order = [u for u in UNITS if army.get(u)]                     # ordre du jeu : JSN, SN, NE, JS, S, C...
    hp = {u: UNITS[u][0] + (UNITS[u][0] * bouclier + 5) // 10 for u in order}   # vie arrondie par unité (toolzzz)
    att = {u: UNITS[u][1] * (1 + 0.1 * armes) for u in order}
    pool = {u: army[u] * hp[u] for u in order}
    preys = [(PREY[i][1], PREY[i][2], prey[i] * PREY[i][2]) for i in range(len(PREY)) if prey[i]]
    p_pool = [p[2] for p in preys]
    for rnd in range(1, 501):
        d_us = sum(pool[u] / hp[u] * att[u] for u in order)
        d_pr = sum(p_pool[j] / preys[j][1] * preys[j][0] for j in range(len(preys)))
        life = sum(p_pool)
        if d_us <= 1e-9 or life <= 1e-9:
            break
        if rnd == 1 and d_us >= life:                  # tuées d'un coup : réplique réduite
            r = d_us / life
            d_pr *= 0.1 if r > 3 else 0.3 if r > 2 else 0.5 if r > 1.5 else 1
        d = d_us
        for j in range(len(p_pool)):
            t = min(p_pool[j], d)
            p_pool[j] -= t
            d -= t
        d = d_pr
        for u in order:
            t = min(pool[u], d)
            pool[u] -= t
            d -= t
    win = sum(p_pool) <= 1e-9 and sum(pool.values()) > 1e-9
    if not win:
        return {u: army[u] for u in order}
    return {u: min(army[u], math.floor(army[u] - pool[u] / hp[u] + 0.5 - 1e-9)) for u in order}


def hunt_stats(army, tdc, amount, armes=0, bouclier=0, n=400, seed=1):
    """Pertes réelles sur n tirages : (moyenne, 9 fois sur 10 au plus, pire)."""
    rng = random.Random(seed * 100003 + int(tdc) * 1009 + amount)
    losses = sorted(fight(army, draw_prey(tdc, amount, rng), armes, bouclier) for _ in range(n))
    return sum(losses) / n, losses[int(0.9 * (n - 1))], losses[-1]


def best_sizes(army, tdc, armes=0, bouclier=0, max_losses=(1, 2, 3), n=400):
    """Pour chaque nombre de pertes L : la plus grande chasse avec ≤ L pertes 9 fois sur 10 et L + 0,05 en moyenne.

    Renvoie {L: (taille, moyenne, pire)}.
    """
    best, misses = {}, 0
    for amount in range(1, 400):
        mean, p90, worst = hunt_stats(army, tdc, amount, armes, bouclier, n)
        ok = False
        for lim in max_losses:
            if p90 <= lim and mean <= lim + 0.05:
                best[lim] = (amount, mean, worst)
                ok = True
        misses = 0 if ok else misses + 1
        if misses >= 6:                                # plus aucun palier atteignable au-delà
            break
    return best


_SIZE_CACHE = {}


def planned_size(army, tdc, armes=0, bouclier=0, losses=1):
    """Taille de chasse pour viser `losses` pertes (9 fois sur 10), mise en cache par tranches (armée à 10 unités près,
    TDC à 25 cm² près) pour que le simulateur reste rapide. None si aucune taille ne tient."""
    bucket = {u: n // 10 * 10 for u, n in army.items() if n >= 10}
    key = (tuple(sorted(bucket.items())), int(tdc) // 25 * 25, armes, bouclier, losses)
    if key not in _SIZE_CACHE:
        best = best_sizes(bucket, key[1], armes, bouclier, (losses,), n=200) if bucket else {}
        _SIZE_CACHE[key] = best[losses][0] if losses in best else None
    return _SIZE_CACHE[key]

