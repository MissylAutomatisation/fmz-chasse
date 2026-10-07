"""/niveau-armes : niveau d'Armes rentable selon l'armée et l'unité pondue.

Paramètres : onglet « calcul manuel » du classeur BDD, intégrés ici (instantané, pas de lecture du sheet).
Modèle : passer d'Armes n−1 à n coûte C(n) = 80 × 2^(n−1) ouvrières, soit C(n) × 60 s de ponte. Pendant ce temps,
on aurait pondu U = C(n) × 60 / t unités (continu, pas d'arrondi), qui frappent à a × (1 + (n−1)/10).
Le niveau rapporte 10 % de la FdF hors bonus (HB) de l'armée, donc il est rentable si
HB ≥ S(n) = plafond(C(n) × 60 / t × a × (n + 9)). Seul S(n) est arrondi.
"""
import asyncio
import base64
from dataclasses import dataclass
from fractions import Fraction
import logging
import math
import re
import time
import unicodedata

import discord
from discord import app_commands

logger = logging.getLogger("niveau_armes")

# Onglet « calcul manuel » : [nom, attaque HB, ponte de base (s), alias regex sur le texte normalisé].
# Abréviations ajoutées aux alias : JSN, SN, NE, JS, S, C, CE, A, AE, SE, Tk, TkE, Tu, TuE, OV.
DEFAULT_DATA = {
    "ranges": [
        [
            ["Ouvrière", 0, 60, r"ouvrieres?|ouvs?|ovs?"],
            ["Jeune Soldate Naine", 3, 300, r"jeunes? soldates? naines?|jsns?"],
            ["Soldate Naine", 5, 450, r"soldates? naines?|sns?"],
            ["Naine d’élite", 7, 570, r"naines? d[' ]?elites?|nes?"],
            ["Jeune Soldate", 10, 740, r"jeunes? soldates?|js"],
            ["Soldate", 15, 1000, r"soldates?|s"],
            ["Concierge", 1, 1410, r"concierges?|c"],
            ["Concierge d’élite", 1, 1410, r"concierges? (?:d[' ]?)?elites?|ces?"],
            ["Artilleuse", 30, 1440, r"artilleuses?|a"],
            ["Artilleuse d’élite", 35, 1520, r"artilleuses? (?:d[' ]?)?elites?|aes?"],
            ["Soldate d’élite", 24, 1450, r"soldates? (?:d[' ]?)?elites?|ses?"],
            ["Tank", 55, 1860, r"tanks?|tks?"],
            ["Tank d’élite", 80, 1860, r"tanks? (?:d[' ]?)?elites?|tkes?"],
            ["Tueuse", 50, 2740, r"tueuses?|tus?"],
            ["Tueuse d’élite", 55, 2740, r"tueuses? (?:d[' ]?)?elites?|tues?"],
        ],
        [[f"Arme {n}", 80 * 2 ** (n - 1)] for n in range(1, 51)],   # coût du passage n−1 -> n (sheet : niveaux 1 à 50)
        [[60]],                                                     # ponte de base d'une ouvrière (s)
    ]
}

# Menu limité à 4 unités pondues ; l'armée accepte toutes les unités. (libellé, nom de l'emoji, emoji de secours)
CHOICES = (
    ("Jeunes Soldates Naines", "armes_jsn_gnome", "🧙‍♂️"),
    ("Jeunes Soldates", "armes_js_casque", "🪖"),
    ("Tanks", "armes_tank", "🛡️"),
    ("Tueuses d’élite", "armes_tueuse_boss", "👹"),
)
TIMEOUT = 300                                                       # une question expire après 5 min


class ArmesError(ValueError):
    """Erreur lisible par le joueur."""


def normalize(text: str) -> str:
    """Minuscules, sans accents, apostrophes droites, espaces (insécables compris) réduits à un seul."""
    text = text.lower().replace("’", "'").replace("‘", "'")
    text = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^\S\n]+", " ", text).strip()


@dataclass(frozen=True)
class Unit:
    name: str
    attack: Fraction
    seconds: Fraction
    alias: str


@dataclass(frozen=True)
class WeaponsData:
    units: tuple[Unit, ...]
    costs: tuple[tuple[int, Fraction], ...]
    worker_seconds: Fraction

    def unit(self, name: str) -> Unit:
        normalized = normalize(name)
        for unit in self.units:
            if normalized == normalize(unit.name) or re.fullmatch(unit.alias, normalized):
                return unit
        raise ArmesError(f"Unité inconnue : « {name.strip()} ». Utilise le nom complet ou l'abréviation (JSN, JS, Tk…).")


def decode_data(payload: dict) -> WeaponsData:
    try:
        unit_rows, cost_rows, worker_rows = payload["ranges"]
        units = tuple(Unit(str(r[0]), Fraction(str(r[1])), Fraction(str(r[2])), str(r[3])) for r in unit_rows)
        costs = tuple((int(re.fullmatch(r"Arme (\d+)", str(r[0])).group(1)), Fraction(str(r[1]))) for r in cost_rows)
        seconds = Fraction(str(worker_rows[0][0]))
        if not units or len(units) > 25 or seconds <= 0 or not costs:
            raise ValueError("Données manquantes")
        if not any(u.attack > 0 for u in units) or len({u.name for u in units}) != len(units):
            raise ValueError("Unités invalides")
        for u in units:
            if u.attack < 0 or u.seconds <= 0:
                raise ValueError("Statistiques invalides")
            re.compile(u.alias)
        if [n for n, _ in costs] != list(range(1, len(costs) + 1)) or any(c <= 0 for _, c in costs):
            raise ValueError("Coûts invalides")
        return WeaponsData(units, costs, seconds)
    except (KeyError, IndexError, TypeError, ValueError, AttributeError, re.error) as exc:
        raise ArmesError("Les paramètres de « calcul manuel » sont incomplets ou invalides.") from exc


DATA = decode_data(DEFAULT_DATA)


def parse_army(text: str, data: WeaponsData = DATA) -> dict[str, int]:
    """Aucune portion inconnue n'est ignorée : sinon la FdF serait sous-estimée."""
    text = normalize(text).strip(" .\n")
    text = re.sub(r"^(?:armee|troupes)\s*:\s*", "", text)
    army: dict[str, int] = {}
    for part in re.split(r"[,;+\n]+", text):
        part = part.strip(" .")
        if not part:
            continue
        match = re.fullmatch(r"(\d+(?: \d{3})*)\s+(.+)", part)
        if not match:
            raise ArmesError(f"Armée illisible : « {part} ». Exemple : « 600 Jeunes Soldates, 43 Soldates » "
                             "(séparées par des virgules, des + ou des lignes).")
        unit = data.unit(match[2])
        army[unit.name] = army.get(unit.name, 0) + int(match[1].replace(" ", ""))
    if not any(army.values()):
        raise ArmesError("L'armée est vide : indique les quantités et les noms des unités.")
    return army


@dataclass(frozen=True)
class Profitability:
    hb: Fraction
    level: int
    next_level: int | None
    next_hb: int | None


def threshold(data: WeaponsData, unit: Unit, level: int, cost: Fraction) -> int:
    """S(n) = plafond(C(n) × t_o / t × a × (n + 9)) : ponte continue, seul le seuil final est arrondi."""
    return math.ceil(cost * data.worker_seconds / unit.seconds * unit.attack * (level + 9))


def calculate(army: dict[str, int], produced: str, data: WeaponsData = DATA) -> Profitability:
    unit = data.unit(produced)
    if unit.attack <= 0:
        raise ArmesError("Les ouvrières n'ont pas de FdF : choisis une unité de combat pondue.")
    hb = sum((data.unit(name).attack * count for name, count in army.items()), Fraction())
    level = 0
    for n, cost in data.costs:
        target = threshold(data, unit, n, cost)
        if hb < target:                                             # égalité au seuil = rentable
            return Profitability(hb, level, n, target)
        level = n
    return Profitability(hb, level, None, None)


def analyse_armes(army_text: str, produced: str, data: WeaponsData = DATA) -> dict:
    """Calcul seul, sans Discord."""
    result = calculate(parse_army(army_text, data), produced, data)
    return {
        "fdf_hb": int(result.hb) if result.hb.denominator == 1 else float(result.hb),
        "niveau_max": result.level,
        "niveau_suivant": result.next_level,
        "cible_hb": result.next_hb,
        "unite_produite": data.unit(produced).name,
    }


def fmt(value) -> str:
    value = Fraction(value)
    if value.denominator == 1:
        return f"{int(value):,}".replace(",", " ")
    return f"{float(value):,.2f}".replace(",", " ").replace(".", ",")


def result_embed(army: dict[str, int], produced: str, data: WeaponsData = DATA) -> discord.Embed:
    result = calculate(army, produced, data)
    embed = discord.Embed(title="Rentabilité des armes", color=discord.Color.blurple())
    embed.add_field(name="Unité produite", value=data.unit(produced).name, inline=False)
    embed.add_field(name="FdF actuelle hors bonus (HB)", value=fmt(result.hb), inline=False)
    embed.add_field(name="Niveau maximal rentable",
                    value=f"Armes {result.level}" if result.next_level else f"Au moins Armes {result.level}",
                    inline=False)
    if result.next_level:
        embed.add_field(name=f"FdF HB cible pour Armes {result.next_level}", value=fmt(result.next_hb), inline=False)
    else:
        embed.add_field(name="Niveau suivant", value="Au-delà des niveaux disponibles dans la BDD.", inline=False)
    embed.set_footer(text="Ponte continue · paramètres « calcul manuel » · arrondi final uniquement")
    return embed


class WeaponsEmojis:
    """Emojis d'application : créés une fois, réutilisés aux redémarrages ; pictogrammes de secours sinon."""

    def __init__(self, client: discord.Client):
        self.client = client
        self.values: dict[str, discord.Emoji] = {}
        self.lock = asyncio.Lock()
        self.loaded = False

    async def ensure(self):
        async with self.lock:
            if self.loaded:
                return
            self.loaded = True                                      # un seul essai : pas d'appel HTTP à chaque commande
            try:
                existing = {e.name: e for e in await self.client.fetch_application_emojis()}
                for _, name, _ in CHOICES:
                    emoji = existing.get(name)
                    if emoji is None:
                        emoji = await self.client.create_application_emoji(
                            name=name, image=base64.b64decode(EMOJI_PNG[name]))
                    self.values[name] = emoji
                logger.info("Emojis de /niveau-armes prêts")
            except (discord.HTTPException, discord.MissingApplicationID, OSError):
                logger.exception("Emojis de /niveau-armes indisponibles : pictogrammes de secours")


class Sessions:
    """Une question en cours par joueur ; une nouvelle armée clôt l'ancienne."""

    def __init__(self):
        self.pending: dict[int, "UnitView"] = {}

    async def replace(self, user_id: int, view: "UnitView"):
        old = self.pending.get(user_id)
        self.pending[user_id] = view
        if old is not None:
            await old.expire()

    def done(self, view: "UnitView"):
        if self.pending.get(view.owner_id) is view:
            del self.pending[view.owner_id]


class UnitModal(discord.ui.Modal, title="Unité que tu produis"):
    unit_name = discord.ui.TextInput(label="Nom de l'unité", placeholder="Jeune Soldate, Jeunes Soldates ou JS",
                                     max_length=100)

    def __init__(self, view: "UnitView"):
        super().__init__()
        self.selection_view = view

    async def on_submit(self, interaction: discord.Interaction):
        await self.selection_view.finish(interaction, self.unit_name.value)


class UnitSelect(discord.ui.Select):
    def __init__(self, data: WeaponsData, emojis: dict):
        super().__init__(placeholder="Quelle unité produis-tu ?", row=0, options=[
            discord.SelectOption(label=label, value=data.unit(label).name, emoji=emojis.get(name, fallback))
            for label, name, fallback in CHOICES
        ])

    async def callback(self, interaction: discord.Interaction):
        await self.view.finish(interaction, self.values[0])


class UnitView(discord.ui.View):
    def __init__(self, owner_id: int, army: dict[str, int], sessions: Sessions, emojis: dict, data: WeaponsData = DATA):
        super().__init__(timeout=TIMEOUT)
        self.owner_id = owner_id
        self.army = army
        self.data = data
        self.sessions = sessions
        self.message = None
        self.finished = False
        self.expires = time.monotonic() + TIMEOUT                   # le timeout de View repart à chaque clic, pas celui-ci
        self.lock = asyncio.Lock()
        self.add_item(UnitSelect(data, emojis))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Ce calcul appartient à un autre joueur. Lance `/niveau-armes` pour le tien.", ephemeral=True)
            return False
        return True

    def complete(self):
        self.finished = True
        self.stop()
        self.sessions.done(self)

    async def finish(self, interaction: discord.Interaction, name: str):
        if not await self.interaction_check(interaction):          # le formulaire texte ne passe pas par la View
            return
        async with self.lock:
            if self.finished or time.monotonic() >= self.expires:
                await interaction.response.send_message(
                    "Cette question est terminée ou expirée. Relance `/niveau-armes`.", ephemeral=True)
                return
            try:
                embed = result_embed(self.army, name, self.data)
            except ArmesError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
            await interaction.response.defer()                      # le formulaire n'a pas toujours le message d'origine
            await self.message.edit(content=None, embed=embed, view=None)
            self.complete()

    @discord.ui.button(label="Saisir le nom de l'unité", style=discord.ButtonStyle.secondary, row=1)
    async def type_unit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(UnitModal(self))

    async def expire(self):
        async with self.lock:
            if self.finished:
                return
            self.complete()
            if self.message:
                try:
                    await self.message.edit(content="Question expirée. Relance `/niveau-armes`.", view=None)
                except discord.HTTPException:
                    pass

    async def on_timeout(self):
        await self.expire()


class ArmyModal(discord.ui.Modal, title="Rentabilité des armes"):
    army_text = discord.ui.TextInput(
        label="Colle ton armée (quantités et unités)", style=discord.TextStyle.paragraph,
        placeholder="600 Jeunes Soldates Naines, 236 SN, 700 JS…", max_length=4000)

    def __init__(self, emojis: WeaponsEmojis, sessions: Sessions):
        super().__init__()
        self.emojis = emojis
        self.sessions = sessions

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            army = parse_army(self.army_text.value)
        except ArmesError as exc:
            await interaction.followup.send(f"❌ {exc}\nRelance `/niveau-armes` pour corriger.", ephemeral=True)
            return
        await self.emojis.ensure()
        view = UnitView(interaction.user.id, army, self.sessions, self.emojis.values)
        await self.sessions.replace(interaction.user.id, view)
        view.message = await interaction.followup.send("Quelle unité produis-tu ?", view=view, ephemeral=True, wait=True)


def setup(client: discord.Client, tree: app_commands.CommandTree) -> WeaponsEmojis:
    """Ajoute /niveau-armes à l'arbre du bot. Ne synchronise pas : à faire une fois toutes les commandes ajoutées."""
    emojis = WeaponsEmojis(client)
    sessions = Sessions()

    @tree.command(name="niveau-armes", description="Niveau d'Armes rentable et FdF HB du niveau suivant")
    async def niveau_armes(interaction: discord.Interaction):
        await interaction.response.send_modal(ArmyModal(emojis, sessions))

    return emojis


# Images 128×128 des 4 emojis du menu (PNG en base64) : nain de jardin, casque vert, tank, boss.
EMOJI_PNG = {
  "armes_jsn_gnome": "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",
  "armes_js_casque": "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",
  "armes_tank": "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",
  "armes_tueuse_boss": "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"
}
