"""Bot Discord « Chasse » : lit des salons dédiés (CHANNEL_ID=id1,id2) ; chaque message (armée, Armes, Bouclier, TDC) reçoit le tableau du
risque selon la taille de chasse ; une armée seule reçoit le niveau d'Armes rentable ; « ov 15000 » reçoit la rentabilité
de l'Étable à pucerons. Ce qui manque dans le message (armée, Armes, Bouclier) est pris dans la fiche du joueur."""
import asyncio
import io
import logging
import os

import discord
from discord import app_commands
from dotenv import load_dotenv

import fiches
import niveau_armes
import profil
import renta_puceron
import risque

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

intents = discord.Intents.default()
intents.message_content = True                                 # à activer aussi sur le portail Discord
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
armes_emojis = niveau_armes.setup(client, tree)                # /niveau-armes
renta_puceron.setup(tree)                                      # /renta puceron
CHANNEL_IDS = {int(c) for c in os.getenv("CHANNEL_ID", "").replace(" ", "").split(",") if c}   # « id1,id2 » : un salon par serveur
SILENT_CHANNEL_IDS = {1556337362211053741}                     # réponses sans notification
PROFIL_CHANNEL_IDS = {1559888062430052474}                     # fiche du joueur -> base + Google Sheet
try:
    profil_sheet = profil.from_env()
except Exception:
    logging.exception("Google Sheet des profils inaccessible : copie dans le sheet désactivée")
    profil_sheet = None
fiches_db = fiches.Fiches()


ALLIANCE = os.getenv("ALLIANCE", "OUAF")


@tree.command(name="niveau-joueur", description="Export CSV des fiches OUAF : étable, champi, ouvrières")
async def niveau_joueur(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    lignes = [{profil.LABELS[f]: fiche[f] for f in ("pseudo", "ov", "champi", "puceron") if fiche[f] is not None}
              for fiche in fiches_db.all()]
    texte, avec_ids = await asyncio.to_thread(profil.export, lignes, ALLIANCE)
    note = "" if avec_ids else "\n⚠️ API du jeu injoignable : player_id vides, membres sans fiche manquants."
    apercu = f"\n```csv\n{texte}```" if len(texte) < 1800 else ""     # copiable sur mobile ; limite Discord 2 000
    fichier = discord.File(io.BytesIO(texte.encode("utf-8")), filename="niveau_joueur.csv")
    await interaction.followup.send(f"📄 {texte.count(chr(10)) - 1} joueurs{note}{apercu}", file=fichier,
                                    ephemeral=True)


async def enregistrer(user: discord.abc.User, values: dict) -> bool:
    """Fiche mise à jour dans la base (qui fait foi), puis copiée dans le sheet. False si la copie a échoué."""
    fiches_db.save(user.id, user.display_name, values)
    if profil_sheet is None:
        return False
    try:
        await asyncio.to_thread(profil_sheet.save, user.id, user.display_name, values)
        return True
    except Exception:
        logging.exception("copie de la fiche dans le sheet impossible pour %s", user.id)
        return False


async def importer_sheet():
    """Base vide (premier lancement, machine de secours) : remplie depuis le sheet."""
    if profil_sheet is None or not fiches_db.is_empty():
        return
    try:
        n = fiches_db.import_sheet(await asyncio.to_thread(profil_sheet.fiches))
        logging.info("%s fiches importées depuis le sheet", n)
    except Exception:
        logging.exception("import des fiches depuis le sheet impossible")


async def setup_hook():
    await importer_sheet()
    await tree.sync()                                          # toutes les commandes sont déjà dans l'arbre
client.setup_hook = setup_hook


@client.event
async def on_ready():
    logging.info("Connecté en tant que %s, salons %s", client.user, sorted(CHANNEL_IDS))
    await armes_emojis.ensure()


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if message.channel.id in PROFIL_CHANNEL_IDS:
        await on_profil(message)
        return
    if message.channel.id not in CHANNEL_IDS:
        return
    silent = message.channel.id in SILENT_CHANNEL_IDS
    if await niveau_armes.answer_unit_name(message, silent):  # réponse à « Quelle unité produis-tu ? »
        return
    if await renta_puceron.answer_message(message, silent):   # « ov 15000 » : rentabilité des pucerons
        return
    army = risque.army_only(message.content)
    if army:                                                   # armée seule : niveau d'Armes rentable
        asyncio.create_task(enregistrer(message.author, {"armee": army}))     # la dernière armée donnée fait foi
        await niveau_armes.ask_in_channel(message, army, armes_emojis, silent)
        return
    asyncio.create_task(enregistrer_chasse(message))
    async with message.channel.typing():                       # le calcul prend quelques secondes
        try:
            reply = await asyncio.to_thread(risque.answer, message.content, fiches_db.get(message.author.id))
        except Exception:
            logging.exception("calcul impossible pour %r", message.content)
            reply = "❌ Erreur pendant le calcul. Vérifie le texte collé."
    silent = reply == risque.ENORME_TEUB or message.channel.id in SILENT_CHANNEL_IDS   # pas de notification
    await message.reply(reply, mention_author=False, silent=silent)


async def enregistrer_chasse(message: discord.Message):
    """Armée, Armes, Bouclier et VC donnés dans le salon chasse remplacent ceux de la fiche (le TDC et le nombre de
    chasses ne sont jamais gardés)."""
    try:
        found = risque.read(message.content)
    except risque.ParseError:
        return
    values = {key: found[k] for key, k in (("armee", "army"), ("armes", "armes"), ("bouclier", "bouclier"), ("vc", "vc"))
              if found[k] is not None}
    if values:
        await enregistrer(message.author, values)


async def on_profil(message: discord.Message):
    try:
        values = profil.parse(message.content)
    except profil.ProfilError as e:
        await message.reply(str(e), mention_author=False, silent=True)
        return
    try:
        copie = await enregistrer(message.author, values)
    except Exception:
        logging.exception("écriture de la fiche impossible pour %r", message.content)
        await message.reply("❌ Pas enregistré (erreur de la base). Préviens un admin.", mention_author=False,
                            silent=True)
        return
    note = "" if copie else "\n⚠️ Copie dans le Google Sheet en échec (la fiche du bot est bien à jour)."
    await message.reply(f"✅ Enregistré : {profil.summary(values)}{note}", mention_author=False, silent=True)


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token or not CHANNEL_IDS:
        raise SystemExit("DISCORD_TOKEN ou CHANNEL_ID manquant : les mettre dans le fichier .env")
    client.run(token, log_handler=None)
