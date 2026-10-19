"""Fiches des joueurs (pseudo, ov, Champignonnière, Étable, Armes, Bouclier, armée) dans une base SQLite locale.

La base fait foi ; le Google Sheet en est une copie mise à jour à chaque enregistrement. Base vide au démarrage :
elle est remplie depuis le sheet (premier lancement, ou machine de secours sans base)."""
import json
import os
import sqlite3
import threading
from pathlib import Path

import profil

DEFAULT_PATH = Path(__file__).resolve().parent / "fiches.db"     # FICHES_DB dans .env pour un autre chemin
COLUMNS = ("pseudo", "ov", "champi", "puceron", "armes", "bouclier", "armee", "vc")


class Fiches:
    """Une ligne par compte Discord. sqlite3 est rapide : appelable directement depuis le bot."""

    def __init__(self, path: str | None = None):
        path = path or os.getenv("FICHES_DB") or str(DEFAULT_PATH)
        self.lock = threading.Lock()                           # une connexion partagée entre le bot et ses threads
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS fiches (
            discord_id TEXT PRIMARY KEY, nom TEXT, pseudo TEXT, ov INTEGER, champi INTEGER, puceron INTEGER,
            armes INTEGER, bouclier INTEGER, armee TEXT, armee_maj TEXT, maj TEXT, vc INTEGER)""")
        known = {row[1] for row in self.db.execute("PRAGMA table_info(fiches)")}
        if "vc" not in known:                                  # base créée avant la VC
            self.db.execute("ALTER TABLE fiches ADD COLUMN vc INTEGER")
        self.db.commit()

    def get(self, discord_id: int) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM fiches WHERE discord_id = ?", (str(discord_id),)).fetchone()
        return _fiche(row) if row else None

    def all(self) -> list[dict]:
        with self.lock:
            return [_fiche(row) for row in self.db.execute("SELECT * FROM fiches")]

    def is_empty(self) -> bool:
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM fiches").fetchone()[0] == 0

    def save(self, discord_id: int, nom: str, values: dict, date: str | None = None) -> None:
        """Seuls les champs donnés changent ; une nouvelle armée remplace l'ancienne et note sa date."""
        date = date or profil.now_paris().strftime("%d/%m/%Y %H:%M")
        cells = {k: (json.dumps(v) if k == "armee" else v) for k, v in values.items() if k in COLUMNS}
        cells.update(nom=nom, maj=date)
        if "armee" in values:
            cells["armee_maj"] = date
        names = list(cells)
        with self.lock:
            self.db.execute(f"INSERT INTO fiches (discord_id, {', '.join(names)}) VALUES (?{', ?' * len(names)}) "
                            f"ON CONFLICT(discord_id) DO UPDATE SET {', '.join(f'{n} = excluded.{n}' for n in names)}",
                            [str(discord_id), *cells.values()])
            self.db.commit()

    def import_sheet(self, rows: list[dict]) -> int:
        """Lignes du sheet {titre: valeur} -> fiches ; renvoie le nombre de fiches importées."""
        n = 0
        for row in rows:
            uid = str(row.get(profil.ID_DISCORD, "")).strip()
            if not uid.isdigit():
                continue
            values = {}
            for field in COLUMNS:
                raw = str(row.get(profil.LABELS[field], "")).strip()
                if not raw:
                    continue
                if field == "pseudo":
                    values[field] = raw
                elif field == "armee":
                    army = profil.army_of(raw)
                    if army:
                        values[field] = army
                else:
                    values[field] = profil.entier(raw)
            self.save(int(uid), str(row.get(profil.NOM_DISCORD, "")), values,
                      date=str(row.get(profil.DATE, "")).strip() or None)
            n += 1
        return n


def _fiche(row: sqlite3.Row) -> dict:
    fiche = dict(row)
    fiche["armee"] = json.loads(fiche["armee"]) if fiche["armee"] else None
    return fiche
