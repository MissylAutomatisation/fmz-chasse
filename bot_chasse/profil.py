"""Salon « profil » : chaque joueur donne ses ouvrières, sa Champignonnière et son Étable à pucerons ; le bot met à jour
sa ligne dans un Google Sheet (une ligne par compte Discord)."""
import os
import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

FIELDS = ("ov", "champi", "puceron")
LABELS = {"ov": "Ouvrières", "champi": "Champignonnière", "puceron": "Étable à pucerons"}
HEADER = ["Joueur", "ID Discord", LABELS["ov"], LABELS["champi"], LABELS["puceron"], "Mis à jour"]
COLUMN = {"ov": 3, "champi": 4, "puceron": 5}                 # colonnes 1-indexées du sheet

# Mots-clés après normalisation (minuscules, sans accents) ; « étable à pucerons » est ramené à « puceron » avant.
KEYWORD = r"(?P<kw>ouvri\w*|ouv|ovs?|champi\w*|champ|puc\w*|etables?)"
NUMBER = r"(?P<num>\d{1,3}(?:[ .,']\d{3})+(?!\d)|\d+)"     # 1234567, 1 234 567, 1.234.567
AFTER = re.compile(rf"\b{KEYWORD}\b\s*(?:[:=]|lvl|lv|niv(?:eau|\.)?|n°)?\s*{NUMBER}")
BEFORE = re.compile(rf"(?<![\d.,']){NUMBER}\s*{KEYWORD}\b")

USAGE = ("❌ Je n'ai rien compris. Écris par exemple :\n`ov 1 234 567 champi 12 puceron 8`\n"
         "Tu peux n'en donner qu'un ou deux (ex. `champi 13`).")


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


def parse(text: str) -> dict[str, int]:
    """« ov 1 234 567 champi 12 puceron 8 » -> {"ov": 1234567, "champi": 12, "puceron": 8}.
    Le nombre peut être après le mot ou, si le message commence par un nombre, avant ; seuls les champs donnés sont
    renvoyés."""
    text = normalize(text)
    found: dict[str, int] = {}
    used: list[range] = []                                     # nombres déjà pris : un nombre ne sert qu'une fois
    order = (BEFORE, AFTER) if re.match(r"\d", text.strip()) else (AFTER, BEFORE)   # « 12 champi 8 puceron »
    for pattern in order:
        for m in pattern.finditer(text):
            field = field_of(m["kw"])
            if field in found or any(m.start("num") in r for r in used):
                continue
            found[field] = int(re.sub(r"\D", "", m["num"]))
            used.append(range(m.start("num"), m.end("num")))
    if not found:
        raise ProfilError(USAGE)
    return found


def summary(values: dict[str, int]) -> str:
    return " · ".join(f"{LABELS[f]} {values[f]:,}".replace(",", " ") for f in FIELDS if f in values)


def now_paris() -> datetime:
    try:
        return datetime.now(ZoneInfo("Europe/Paris"))
    except Exception:                                          # pas de base des fuseaux (Windows sans tzdata)
        return datetime.now()


class ProfilSheet:
    """Une ligne par joueur, retrouvée par son ID Discord (colonne B). gspread est synchrone : appeler dans un thread."""

    def __init__(self, key_file: str, sheet_id: str):
        import gspread                                         # importé ici : le bot démarre même sans gspread
        self.ws = gspread.service_account(key_file).open_by_key(sheet_id).sheet1

    def save(self, user_id: int, name: str, values: dict[str, int]) -> None:
        rows = self.ws.get_all_values()
        if not rows or rows[0][:len(HEADER)] != HEADER:
            self.ws.update(range_name="A1", values=[HEADER])
            rows = [HEADER] + rows[1:]
        index = next((i for i, row in enumerate(rows) if len(row) > 1 and row[1] == str(user_id)), None)
        row = list(rows[index]) if index is not None else ["", str(user_id), "", "", ""]
        row += [""] * (len(HEADER) - len(row))
        row[0] = name
        for field, value in values.items():
            row[COLUMN[field] - 1] = value
        row[5] = now_paris().strftime("%d/%m/%Y %H:%M")
        if index is None:
            self.ws.append_row(row[:len(HEADER)], value_input_option="RAW")
        else:
            self.ws.update(range_name=f"A{index + 1}", values=[row[:len(HEADER)]], value_input_option="RAW")


def from_env() -> ProfilSheet | None:
    """None si le salon ou le sheet n'est pas configuré : le reste du bot tourne quand même."""
    key_file, sheet_id = os.getenv("GSHEET_KEY"), os.getenv("PROFIL_SHEET_ID")
    if not (key_file and sheet_id):
        return None
    return ProfilSheet(key_file, sheet_id)
