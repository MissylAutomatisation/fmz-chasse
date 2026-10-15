"""Salon « profil » : chaque joueur donne son pseudo en jeu, ses ouvrières, sa Champignonnière et son Étable à pucerons ;
le bot met à jour sa ligne dans un Google Sheet (une ligne par compte Discord)."""
import os
import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

FIELDS = ("pseudo", "ov", "champi", "puceron")
LABELS = {"pseudo": "ID In Game", "ov": "Ouvrières", "champi": "Champignonnière", "puceron": "Étable à pucerons"}
NOM_DISCORD, ID_DISCORD, DATE = "Nom Discord", "ID Discord", "Mis à jour"
# Ordre d'un sheet neuf ; ensuite chaque colonne est retrouvée par son titre, où qu'elle soit.
HEADER = [NOM_DISCORD, LABELS["pseudo"], ID_DISCORD, LABELS["ov"], LABELS["champi"], LABELS["puceron"], DATE]

# Pseudo en jeu : un mot (lettres, chiffres, _ - .), casse gardée ; lu avant les nombres puis retiré du texte.
PSEUDO = re.compile(r"\b(?:pseudo|id\s*(?:in\s*game|ig|jeu)|in\s*game|ingame|ig)\b\s*[:=]?\s*(?P<pseudo>[\w.\-]+)",
                    re.IGNORECASE)
BARE_PSEUDO = re.compile(r"\s*(?P<pseudo>[\w.\-]+)\s*[:,;]?\s+")

# Mots-clés après normalisation (minuscules, sans accents) ; « étable à pucerons » est ramené à « puceron » avant.
KEYWORD = r"(?P<kw>ouvri\w*|ouv|ovs?|champi\w*|champ|puc\w*|etables?)"
NUMBER = r"(?P<num>\d{1,3}(?:[ .,']\d{3})+(?!\d)|\d+)"     # 1234567, 1 234 567, 1.234.567
AFTER = re.compile(rf"\b{KEYWORD}\b\s*(?:[:=]|lvl|lv|niv(?:eau|\.)?|n°)?\s*{NUMBER}")
BEFORE = re.compile(rf"(?<![\d.,']){NUMBER}\s*{KEYWORD}\b")

USAGE = ("❌ Je n'ai rien compris. Écris par exemple :\n`pseudo TonPseudo ov 1 234 567 champi 12 puceron 8`\n"
         "Tu peux n'en donner qu'une partie (ex. `champi 13`).")


class ProfilError(ValueError):
    pass


def normalize(text: str) -> str:
    """Minuscules, sans accents, espaces (insécables compris) réduits à un seul."""
    text = "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"\betables? (?:a|aux|de|des)? ?pucerons?\b", "puceron", text)


def field_of(keyword: str) -> str:
    if keyword.startswith(("ouv", "ov")):
        return "ov"
    if keyword.startswith("champ"):
        return "champi"
    return "puceron"


def parse(text: str) -> dict[str, int | str]:
    """« pseudo Missyl ov 1 234 567 champi 12 puceron 8 »
    -> {"pseudo": "Missyl", "ov": 1234567, "champi": 12, "puceron": 8}.
    Le nombre peut être après le mot ou, si le message commence par un nombre, avant ; seuls les champs donnés sont
    renvoyés."""
    found: dict[str, int | str] = {}
    m = PSEUDO.search(text)
    if m:
        found["pseudo"] = m["pseudo"]
        text = text[:m.start()] + " " + text[m.end():]        # un pseudo comme « ovni42 » n'est pas lu comme un nombre
    else:
        # Sans mot-clé, un premier mot qui n'est ni un nombre ni un mot-clé est le pseudo (« DogGyneco ov 63981 »),
        # à condition que la suite donne au moins une valeur : « bonjour » seul reste incompris.
        m = BARE_PSEUDO.match(text)
        if m and not re.fullmatch(KEYWORD, normalize(m["pseudo"])) and not m["pseudo"][0].isdigit():
            rest = parse_numbers(text[m.end():])
            if rest:
                return {"pseudo": m["pseudo"], **rest}
    found.update(parse_numbers(text))
    if not found:
        raise ProfilError(USAGE)
    return found


def parse_numbers(text: str) -> dict[str, int]:
    """Ouvrières, Champignonnière, Étable : seuls les champs trouvés sont renvoyés."""
    found: dict[str, int] = {}
    text = normalize(text)
    used: list[range] = []                                     # nombres déjà pris : un nombre ne sert qu'une fois
    order = (BEFORE, AFTER) if re.match(r"\d", text.strip()) else (AFTER, BEFORE)   # « 12 champi 8 puceron »
    for pattern in order:
        for m in pattern.finditer(text):
            field = field_of(m["kw"])
            if field in found or any(m.start("num") in r for r in used):
                continue
            found[field] = int(re.sub(r"\D", "", m["num"]))
            used.append(range(m.start("num"), m.end("num")))
    return found


def summary(values: dict[str, int | str]) -> str:
    def show(field):
        return values[field] if field == "pseudo" else f"{values[field]:,}".replace(",", " ")
    return " · ".join(f"{LABELS[f]} {show(f)}" for f in FIELDS if f in values)


def now_paris() -> datetime:
    try:
        return datetime.now(ZoneInfo("Europe/Paris"))
    except Exception:                                          # pas de base des fuseaux (Windows sans tzdata)
        return datetime.now()


def column_letter(n: int) -> str:
    """1 -> A, 27 -> AA."""
    letters = ""
    while n:
        n, r = divmod(n - 1, 26)
        letters = chr(65 + r) + letters
    return letters


class ProfilSheet:
    """Une ligne par joueur, retrouvée par son ID Discord ; les colonnes sont retrouvées par leur titre, donc le sheet
    peut être réorganisé ou enrichi à la main sans casser le bot. gspread est synchrone : appeler dans un thread."""

    def __init__(self, key_file: str, sheet_id: str):
        import gspread                                         # importé ici : le bot démarre même sans gspread
        self.ws = gspread.service_account(key_file).open_by_key(sheet_id).sheet1

    def save(self, user_id: int, name: str, values: dict[str, int | str]) -> None:
        rows = self.ws.get_all_values()
        header = [h.strip() for h in rows[0]] if rows else []
        missing = [h for h in HEADER if h not in header]
        if missing:                                            # colonne absente : ajoutée au bout, rien n'est déplacé
            while header and not header[-1]:
                header.pop()
            header += missing
            self.ws.update(range_name="A1", values=[header])
        col = {h: header.index(h) for h in HEADER}
        uid = str(user_id)
        index = next((i for i, row in enumerate(rows[1:], start=1)
                      if len(row) > col[ID_DISCORD] and row[col[ID_DISCORD]].strip() == uid), None)

        cells = {NOM_DISCORD: name, ID_DISCORD: uid, DATE: now_paris().strftime("%d/%m/%Y %H:%M")}
        cells.update({LABELS[field]: value for field, value in values.items()})
        if index is None:
            row = [""] * (max(col.values()) + 1)
            for label, value in cells.items():
                row[col[label]] = value
            self.ws.append_row(row, value_input_option="RAW", table_range="A1")
        else:                                                  # seules les cases du bot sont réécrites
            self.ws.batch_update([{"range": f"{column_letter(col[label] + 1)}{index + 1}", "values": [[value]]}
                                  for label, value in cells.items()], value_input_option="RAW")


    def fiches(self) -> list[dict]:
        """Lignes du sheet en dictionnaires {titre de colonne: valeur}."""
        rows = self.ws.get_all_values()
        if not rows:
            return []
        header = [h.strip() for h in rows[0]]
        return [dict(zip(header, row)) for row in rows[1:]]

    def export(self, alliance: str) -> tuple[str, bool]:
        """(CSV, player_id trouvés). Si l'API est injoignable, l'export part du sheet seul, sans player_id."""
        try:
            joueurs, ok = joueurs_api(), True
        except Exception:
            joueurs, ok = [], False
        return texte_csv(lignes_export(self.fiches(), joueurs, alliance)), ok


def from_env() -> ProfilSheet | None:
    """None si le salon ou le sheet n'est pas configuré : le reste du bot tourne quand même."""
    key_file, sheet_id = os.getenv("GSHEET_KEY"), os.getenv("PROFIL_SHEET_ID")
    if not (key_file and sheet_id):
        return None
    return ProfilSheet(key_file, sheet_id)


# --- Export CSV (/niveau-joueur) ---
EXPORT_HEADER = ["player_id", "pseudo", "etable_puceron", "champi", "ouvriere"]
API_JOUEURS = "https://s5.fourmizzz.fr/api/exports/players/"


def entier(valeur) -> int:
    """« 1 234 567 », « 12 », vide -> entier (0 si vide)."""
    chiffres = re.sub(r"\D", "", str(valeur or ""))
    return int(chiffres) if chiffres else 0


def lignes_export(fiches: list[dict], joueurs: list[dict], alliance: str) -> list[list]:
    """Membres de l'alliance (export API) complétés par les fiches du sheet, pseudo comparé sans la casse.

    Un membre sans fiche a 0 partout ; une fiche dont le pseudo n'est pas dans l'API garde un player_id vide.
    Triées par pseudo."""
    par_pseudo = {j["pseudo"].lower(): j for j in joueurs}
    lignes = {j["pseudo"].lower(): [j["id"], j["pseudo"], 0, 0, 0] for j in joueurs if j["alliance"] == alliance}
    for fiche in fiches:
        pseudo = str(fiche.get(LABELS["pseudo"], "")).strip()
        if not pseudo:
            continue
        joueur = par_pseudo.get(pseudo.lower())
        ligne = lignes.setdefault(pseudo.lower(), [joueur["id"] if joueur else "", joueur["pseudo"] if joueur else pseudo,
                                                   0, 0, 0])
        ligne[2:] = [entier(fiche.get(LABELS["puceron"])), entier(fiche.get(LABELS["champi"])),
                     entier(fiche.get(LABELS["ov"]))]
    return sorted(lignes.values(), key=lambda ligne: str(ligne[1]).lower())


def texte_csv(lignes: list[list]) -> str:
    import csv
    import io
    sortie = io.StringIO()
    ecrivain = csv.writer(sortie, lineterminator="\n")
    ecrivain.writerow(EXPORT_HEADER)
    ecrivain.writerows(lignes)
    return sortie.getvalue()


def joueurs_api() -> list[dict]:
    import json
    import urllib.request
    requete = urllib.request.Request(API_JOUEURS, headers={"User-Agent": "Fmz-Chasse (bot d'alliance)"})
    with urllib.request.urlopen(requete, timeout=30) as reponse:
        return json.load(reponse)
