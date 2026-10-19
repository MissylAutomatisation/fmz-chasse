"""Rentabilité de l'Étable à pucerons : commande /renta puceron et message « ov 15000 » dans les salons chasse.

Capacité de convoi par ouvrière : 10 + 0,5 × niveau (texte de la page Commerce). Coût en ov modélisé, non vérifié :
niveau 1 = Communication 1 à 3 (560 ov), puis 320 × 2^n par niveau ; le bois de l'étable n'est pas compté.
"""
import asyncio
from dataclasses import dataclass
import logging
import re
import time
import unicodedata

import discord
from discord import app_commands


async def _report_ui_error(interaction, error):
    logging.getLogger("renta_puceron").error(
        "Erreur dans l’interface pucerons",
        exc_info=(type(error), error, error.__traceback__),
    )
    message = "Une erreur technique a empêché le calcul. Réessaie ou contacte un administrateur."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(
                message, ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
            )
        else:
            await interaction.response.send_message(
                message, ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
            )
    except discord.HTTPException:
        logging.getLogger("renta_puceron").exception("Impossible de signaler l’erreur au joueur")


# CALCULS ET VALIDATION DES SAISIES

class PuceronsInputError(ValueError):
    """Saisie incorrecte pouvant être expliquée au joueur."""

def parse_workers(text: str) -> int:
    normalized = text.strip().replace("\u00a0", " ").replace("\u202f", " ")
    if not re.fullmatch(
        r"(?:[0-9]+|[0-9]{1,3}(?: [0-9]{3})+|[0-9]{1,3}(?:\.[0-9]{3})+)",
        normalized,
    ):
        raise PuceronsInputError(
            "Nombre d’ouvrières invalide. Saisis un entier positif ou nul, "
            "par exemple 15000, 15 000 ou 15.000. "
            "Les décimales, signes et suffixes ne sont pas acceptés."
        )
    digits = normalized.replace(" ", "").replace(".", "")
    if len(digits) > 100:
        raise PuceronsInputError("Le nombre d’ouvrières est limité à 100 chiffres, hors séparateurs.")
    return int(digits)

def parse_workers_message(text: str) -> int | None:
    """Ne reconnaît qu’un message entier « ov 15000 » ou « 15000 ov » (ou ouvrières)."""
    normalized = "".join(
        char for char in unicodedata.normalize("NFD", text.casefold())
        if not unicodedata.combining(char)
    ).strip().replace("\u00a0", " ").replace("\u202f", " ")
    word = r"(?:ov|ouvriers?|ouvrieres?|ouvieres?)"
    match = (re.fullmatch(rf"{word} *:? *([0-9][0-9 .]*)", normalized)
             or re.fullmatch(rf"([0-9][0-9 .]*) *{word}", normalized))
    if not match:
        return None
    try:
        return parse_workers(match[1].strip())
    except PuceronsInputError:
        # Le dialogue ordinaire et les formats non reconnus restent sans réponse.
        return None

def parse_pucerons_message(text: str) -> tuple[int, int | None] | None:
    """Accepte les anciens formats et le suffixe explicite « niveau N »."""
    workers = parse_workers_message(text)
    if workers is not None:
        return workers, None
    match = re.fullmatch(r"(.+?) +niveau +([0-9]{1,16})", text.strip(), re.IGNORECASE)
    if not match:
        return None
    workers = parse_workers_message(match[1])
    if workers is None:
        return None
    try:
        level = int(match[2])
        validate_current_level(level)
    except PuceronsInputError:
        return None
    return workers, level

def validate_current_level(level: int) -> None:
    # Même plage d’entiers exacts que les options INTEGER de Discord.
    if type(level) is not int or not 0 <= level <= 2**53 - 1:
        raise PuceronsInputError(
            "Le niveau actuel doit être un entier positif ou nul, au maximum 9007199254740991."
        )

def parse_current_level(text: str) -> int:
    text = text.strip()
    if not re.fullmatch(r"[0-9]{1,16}", text):
        raise PuceronsInputError("Indique ton niveau actuel avec un entier positif ou nul (0 si non construite).")
    level = int(text)
    validate_current_level(level)
    return level

def minimum_workers(target_level: int) -> int:
    """Le minimum entier strictement rentable pour atteindre le niveau cible."""
    if target_level < 1:
        raise ValueError("Le niveau cible doit être au moins 1.")
    if target_level == 1:
        # Scénario de référence : trois recherches à financer, sans coûts inventés.
        return 11_761
    previous_level = target_level - 1
    return (6720 + 320 * previous_level) * (1 << previous_level) + 1

def marginal_cost(target_level: int) -> int:
    """Coût d’un seul passage, en équivalents ouvrières, pas son coût cumulé."""
    if target_level < 1:
        raise ValueError("Le niveau cible doit être au moins 1.")
    if target_level == 1:
        # Coût GLOBAL implicite du scénario : à l’égalité,
        # 11760 × 10 = (11760 − c) × 10,5, donc c = 560.
        # Cela ne donne ni les coûts individuels des recherches ni les prix réels.
        return 560
    return 320 * (1 << (target_level - 1))

@dataclass(frozen=True)
class PuceronsResult:
    workers: int
    level: int
    next_level: int
    next_minimum: int
    missing: int
    current_level: int | None = None

    @property
    def current_capacity_twice(self) -> int | None:
        """Capacité au niveau déclaré, sans sacrifice hypothétique."""
        if self.current_level is None:
            return None
        return self.workers * (20 + self.current_level)

    @property
    def projected_level(self) -> int | None:
        if self.current_level is None:
            return None
        # Après chaque achat, le passage suivant dispose d’un effectif réduit.
        # Le maximum à effectif constant borne la boucle et évite d’exponentier
        # un niveau déclaré arbitrairement grand.
        level, remaining = self.current_level, self.workers
        while level < self.level:
            cost = marginal_cost(level + 1)
            before = remaining * (20 + level)
            after = (remaining - cost) * (21 + level)
            if remaining < cost or after <= before:
                break
            remaining -= cost
            level += 1
        return level

    @property
    def projected_cost(self) -> int | None:
        """Coût cumulé simulé ; distinct du dernier coût marginal."""
        if self.current_level is None:
            return None
        # Somme géométrique des passages n → n+1 pour n ≥ 1.
        # Ne pas exponentier un niveau déclaré supérieur au maximum calculé.
        target = self.projected_level
        if self.current_level >= target:
            return 0
        start = max(1, self.current_level)
        cost = 320 * ((1 << target) - (1 << start))
        return cost + (marginal_cost(1) if self.current_level == 0 else 0)

    @property
    def projected_remaining_workers(self) -> int | None:
        if self.projected_cost is None:
            return None
        return self.workers - self.projected_cost

    @property
    def projected_capacity_twice(self) -> int | None:
        if self.projected_remaining_workers is None:
            return None
        return self.projected_remaining_workers * (20 + self.projected_level)

    @property
    def projected_gain_twice(self) -> int | None:
        if self.current_level is None:
            return None
        return self.projected_capacity_twice - self.current_capacity_twice

    @property
    def capacity_twice(self) -> int:
        """Capacité multipliée par deux pour ne jamais calculer en flottants."""
        return 20 + self.level

    @property
    def capacity_label(self) -> str:
        whole, half = divmod(self.capacity_twice, 2)
        return f"{whole},5" if half else str(whole)

    @property
    def comparison_from_level(self) -> int:
        return max(0, self.level - 1)

    @property
    def sacrificed_workers(self) -> int:
        return marginal_cost(self.level) if self.level else 0

    @property
    def remaining_workers(self) -> int:
        return self.workers - self.sacrificed_workers

    @property
    def capacity_before_twice(self) -> int:
        return self.workers * (20 + self.comparison_from_level)

    @property
    def capacity_after_twice(self) -> int:
        return self.remaining_workers * self.capacity_twice

    @property
    def capacity_gain_twice(self) -> int:
        return self.capacity_after_twice - self.capacity_before_twice

def calculate_pucerons(workers: int, current_level: int | None = None) -> PuceronsResult:
    if workers < 0:
        raise ValueError("L’effectif doit être positif ou nul.")
    if current_level is not None:
        validate_current_level(current_level)
    level = 0
    next_minimum = minimum_workers(1)
    # Chaque palier compare le même effectif, sans déduire les coûts successifs.
    while workers >= next_minimum:
        level += 1
        next_minimum = minimum_workers(level + 1)
    return PuceronsResult(workers, level, level + 1, next_minimum, next_minimum - workers,
                          current_level)

# BOUTONS ET FENÊTRE DISCORD

class PuceronsLevelModal(discord.ui.Modal, title="Ton niveau actuel de pucerons"):
    level_input = discord.ui.TextInput(
        label="Niveau actuel d’étable à pucerons",
        placeholder="0 si non construite, sinon ton niveau actuel",
        max_length=16,
    )

    def __init__(self, view):
        super().__init__(timeout=300)
        self.level_view = view

    async def on_submit(self, interaction):
        await self.level_view.finish_interaction(interaction, self.level_input.value)

    async def on_timeout(self):
        await self.level_view.expire()

    async def on_error(self, interaction, error):
        await _report_ui_error(interaction, error)

class PuceronsLevelView(discord.ui.View):
    def __init__(self, owner_id, workers, embed_builder, on_done=None, *, exact_embed_builder):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.workers = workers
        self.embed_builder = embed_builder
        self.exact_embed_builder = exact_embed_builder
        self.result = None
        self.on_done = on_done
        self.message = None
        self.finished = False
        self.closed = False
        self.expires = time.monotonic() + 300
        self.lock = asyncio.Lock()

    def complete(self):
        if self.closed:
            return
        self.closed = True
        self.finished = True
        self.stop()
        if self.on_done:
            self.on_done(self)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Cette question appartient à un autre joueur. Envoie ton effectif pour lancer ton calcul.",
                ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
            )
            return False
        return True

    @discord.ui.button(label="Calculer avec mon niveau actuel", style=discord.ButtonStyle.primary)
    async def enter_level(self, interaction, button):
        if not await self.interaction_check(interaction):
            return
        if self.finished or time.monotonic() >= self.expires:
            await interaction.response.send_message(
                "Cette question est terminée ou expirée. Renvoie ton effectif.",
                ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        await interaction.response.send_modal(PuceronsLevelModal(self))

    @discord.ui.button(label="Voir les valeurs exactes", style=discord.ButtonStyle.secondary)
    async def show_exact(self, interaction, button):
        if not await self.interaction_check(interaction):
            return
        async with self.lock:
            if self.closed or time.monotonic() >= self.expires:
                self.complete()
                await interaction.response.send_message(
                    "Cette option a expiré. Renvoie ton effectif.",
                    ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
                )
                return
            result = self.result if self.result is not None else calculate_pucerons(self.workers)
            await interaction.response.send_message(
                embed=self.exact_embed_builder(result),
                ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
            )

    async def finish_interaction(self, interaction, text):
        if not await self.interaction_check(interaction):
            return
        async with self.lock:
            if self.closed or time.monotonic() >= self.expires:
                self.complete()
                await interaction.response.send_message(
                    "Cette question est terminée ou expirée. Renvoie ton effectif.",
                    ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
                )
                return
            if self.finished:
                await interaction.response.send_message(
                    "Ce calcul est déjà terminé. Tu peux consulter les valeurs exactes.",
                    ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
                )
                return
            try:
                level = parse_current_level(text)
            except PuceronsInputError as exc:
                await interaction.response.send_message(
                    str(exc), ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
                )
                return
            result = calculate_pucerons(self.workers, level)
            embed = self.embed_builder(result)
            self.enter_level.disabled = True
            try:
                if self.message is None:
                    await interaction.response.send_message(
                        embed=embed, view=self, allowed_mentions=discord.AllowedMentions.none(),
                    )
                    self.message = await interaction.original_response()
                else:
                    await interaction.response.defer()
                    await self.message.edit(
                        content=None, embed=embed, view=self,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
            except Exception:
                self.enter_level.disabled = False
                raise
            self.result = result
            self.finished = True
            if self.on_done:
                self.on_done(self)

    async def expire(self):
        async with self.lock:
            if self.closed:
                return
            self.complete()
            if self.message:
                try:
                    await self.message.edit(
                        view=None, allowed_mentions=discord.AllowedMentions.none(),
                    )
                except discord.HTTPException:
                    pass

    async def on_timeout(self):
        await self.expire()

    async def on_error(self, interaction, error, item):
        await _report_ui_error(interaction, error)

# PRÉSENTATION ET COMMANDE DISCORD

logger = logging.getLogger("renta_puceron")

def format_integer(value: int) -> str:
    return f"{value:,}".replace(",", " ")

def format_half(value_twice: int) -> str:
    if value_twice < 0:
        return "−" + format_half(-value_twice)
    whole, half = divmod(value_twice, 2)
    return format_integer(whole) + (",5" if half else "")

def format_compact_half(value_twice: int, decimals: int = 3) -> str:
    """Arrondit uniquement l’affichage, sans convertir les calculs en flottants."""
    if value_twice < 0:
        return "−" + format_compact_half(-value_twice, decimals)
    if value_twice < 2000 and (decimals or value_twice < 1999):
        return format_half(value_twice) if decimals else format_integer((value_twice + 1) // 2)
    suffixes = ("", "k", "m", "g", "t", "p", "e", "z", "y", "r", "q")
    exponent = len(str(value_twice // 2)) - 1
    group = exponent // 3
    scale = 1000 ** group
    factor = 10 ** decimals
    rounded = (value_twice * factor + scale) // (2 * scale)
    if rounded >= 1000 * factor:
        group += 1
        scale *= 1000
        rounded = (value_twice * factor + scale) // (2 * scale)
    if group < len(suffixes):
        suffix = suffixes[group]
    else:
        # Au-delà des préfixes SI, garder les entrées de 100 chiffres lisibles.
        scale = 10 ** exponent
        rounded = (value_twice * factor + scale) // (2 * scale)
        if rounded >= 10 * factor:
            exponent += 1
            rounded = factor
        suffix = f"e{exponent}"
    whole, fraction = divmod(rounded, factor)
    decimal = f",{fraction:0{decimals}d}".rstrip("0") if fraction else ""
    return f"{whole}{decimal}{suffix}"

def format_capacity_gain(gain_twice: int, *, exact: bool = False) -> str:
    value = (
        format_half(gain_twice)
        if exact or abs(gain_twice) <= 2_000_000_000
        else format_compact_half(gain_twice, 0)
    )
    return f"{'+' if gain_twice > 0 else ''}{value} rss"

def convoy_table(workers_before, workers_after, capacity_before, capacity_after):
    """Discord n’affiche pas les tableaux Markdown : colonnes en bloc monospace."""
    rows = [
        ("Donnée", "Avant", "Après"),
        ("Ov disponibles", format_compact_half(workers_before * 2, 1), format_compact_half(workers_after * 2, 1)),
        ("Capacité convoi", format_compact_half(capacity_before, 0), format_compact_half(capacity_after, 0)),
    ]
    widths = [max(len(row[i]) for row in rows) for i in range(3)]

    def border(left, joint, right, fill="─"):
        return left + joint.join(fill * width for width in widths) + right

    def row_line(row, header=False):
        cells = [
            f"{value:^{widths[i]}}" if header else
            (f"{value:<{widths[i]}}" if i == 0 else f"{value:>{widths[i]}}")
            for i, value in enumerate(row)
        ]
        return "│" + "│".join(cells) + "│"

    lines = [
        border("┌", "┬", "┐"),
        row_line(rows[0], header=True),
        border("╞", "╪", "╡", fill="═"),
        row_line(rows[1]),
        border("├", "┼", "┤"),
        row_line(rows[2]),
        border("└", "┴", "┘"),
    ]
    return "```\n" + "\n".join(lines) + "\n```"

def known_level_embed(result: PuceronsResult) -> discord.Embed:
    target = result.projected_level
    advancing = target > result.current_level
    embed = discord.Embed(
        title=f"Pucerons — Niveau maximal rentable : {target}",
        description=(
            f"Niveau actuel : **{result.current_level}**\n"
            f"Montée simulée : **niveau {result.current_level} → {target}**\n"
            + ("" if advancing else "Aucune amélioration rentable : maintien du niveau actuel.\n")
            + f"Gain de capacité convoi : **{format_capacity_gain(result.projected_gain_twice)}**\n"
            + convoy_table(result.workers, result.projected_remaining_workers,
                           result.current_capacity_twice, result.projected_capacity_twice)
        ),
        color=discord.Color.green() if advancing else discord.Color.orange(),
    )
    embed.set_footer(
        text="Sacrifices successifs déduits de l’effectif · Coûts modélisés, prix du jeu non vérifiés"
    )
    return embed

def result_embed(result: PuceronsResult) -> discord.Embed:
    if result.current_level is not None:
        return known_level_embed(result)
    title = (
        f"Passage maximal de puceron : {result.comparison_from_level} -> {result.level}"
        if result.level else "Passage maximal de puceron : aucun passage rentable"
    )
    warning = (
        f"Si ton niveau puceron est inférieur à **{result.comparison_from_level}**, "
        "tu dois faire un calcul plus précis."
        if result.level else "Il n’y a aucun passage rentable : maintien au niveau 0."
    )
    embed = discord.Embed(
        title=title,
        description=(
            f"{warning}\n"
            f"Coût du passage : **{format_compact_half(result.sacrificed_workers * 2, 1)} ov**\n"
            f"Gain de capacité convoi : **{format_capacity_gain(result.capacity_gain_twice)}**\n\n"
            + convoy_table(result.workers, result.remaining_workers,
                           result.capacity_before_twice, result.capacity_after_twice)
            + "\n*La quantité d’ouvrières saisie doit correspondre aux ov disponibles "
            "(qui n’exploitent pas le TDC).*"
        ),
        color=discord.Color.green() if result.level else discord.Color.orange(),
    )
    return embed

def exact_values_embed(result: PuceronsResult) -> discord.Embed:
    """Les valeurs sans abréviation sont empilées pour rester lisibles sur mobile."""
    personalized = result.current_level is not None
    summary = result_embed(result)
    if personalized:
        before = result.current_capacity_twice
        after = result.projected_capacity_twice
        remaining = result.projected_remaining_workers
        cost = result.projected_cost
        description = f"Niveau actuel : **{result.current_level}**\n"
        cost_label = "Coût total de la montée"
    else:
        before = result.capacity_before_twice
        after = result.capacity_after_twice
        remaining = result.remaining_workers
        cost = result.sacrificed_workers
        description = ""
        cost_label = "Coût du passage"
    embed = discord.Embed(
        title=summary.title,
        description=description + "**Valeurs exactes — sans arrondi ni abréviation**",
        color=summary.color,
    )
    embed.add_field(name=cost_label, value=f"{format_integer(cost)} ov", inline=False)
    for label, workers, capacity in (
        ("Avant", result.workers, before), ("Après", remaining, after),
    ):
        embed.add_field(
            name=label,
            value=(f"**Ov disponibles**\n{format_integer(workers)}\n"
                   f"**Capacité convoi**\n{format_half(capacity)} rss"),
            inline=False,
        )
    embed.add_field(
        name="Gain de capacité convoi",
        value=format_capacity_gain(after - before, exact=True),
        inline=False,
    )
    embed.set_footer(text="Coûts modélisés, prix du jeu non vérifiés")
    return embed

async def answer_message(message: discord.Message, silent: bool) -> bool:
    """Répond à « ov 15000 » ; False si le message n'est pas un effectif seul."""
    workers = parse_workers_message(message.content)
    if workers is None:
        return False
    key = (message.channel.id, message.author.id)

    def cleanup(view):
        if PENDING.get(key) is view:
            PENDING.pop(key, None)

    view = PuceronsLevelView(message.author.id, workers, result_embed, cleanup,
                             exact_embed_builder=exact_values_embed)
    try:
        view.message = await message.reply(embed=result_embed(calculate_pucerons(workers)), view=view,
                                           mention_author=False, silent=silent,
                                           allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        view.complete()
        logger.exception("Impossible d’afficher la simulation pucerons (salon=%s)", message.channel.id)
        return True
    old = PENDING.get(key)
    PENDING[key] = view                                        # un nouvel effectif remplace la question en attente
    if old:
        await old.expire()
    return True


PENDING: dict[tuple[int, int], PuceronsLevelView] = {}
renta = app_commands.Group(name="renta", description="Calcule la rentabilité des améliorations")


@renta.command(name="puceron", description="Simule un passage de pucerons puis propose un calcul selon ton niveau actuel")
@app_commands.describe(ouvrieres="Nombre d’ouvrières disponibles pour les convois")
async def renta_puceron(interaction: discord.Interaction, ouvrieres: str):
    try:
        workers = parse_workers(ouvrieres)
    except PuceronsInputError as exc:
        await interaction.response.send_message(str(exc), ephemeral=True,
                                                allowed_mentions=discord.AllowedMentions.none())
        return
    view = PuceronsLevelView(interaction.user.id, workers, result_embed, exact_embed_builder=exact_values_embed)
    try:
        await interaction.response.send_message(embed=result_embed(calculate_pucerons(workers)), view=view,
                                                allowed_mentions=discord.AllowedMentions.none())
        view.message = await interaction.original_response()
    except discord.HTTPException:
        view.complete()
        raise


def setup(tree: app_commands.CommandTree):
    tree.add_command(renta)
