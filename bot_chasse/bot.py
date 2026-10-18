"""Bot Discord « Chasse » : lit des salons dédiés (CHANNEL_ID=id1,id2) ; chaque message (armée, Armes, Bouclier, TDC) reçoit le tableau du
risque selon la taille de chasse ; une armée seule reçoit le niveau d'Armes rentable."""
import asyncio
import io
import logging
import os

import discord
from discord import app_commands
from dotenv import load_dotenv

import niveau_armes
import profil
import risque

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

intents = discord.Intents.default()
intents.message_content = True                                 # à activer aussi sur le portail Discord
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
armes_emojis = niveau_armes.setup(client, tree)                # /niveau-armes
CHANNEL_IDS = {int(c) for c in os.getenv("CHANNEL_ID", "").replace(" ", "").split(",") if c}   # « id1,id2 » : un salon par serveur
SILENT_CHANNEL_IDS = {1556337362211053741}                     # réponses sans notification
PROFIL_CHANNEL_IDS = {1559888062430052474}                        # pseudo, ov, Champignonnière, Étable -> Google Sheet
try:
    profil_sheet = profil.from_env()
except Exception:
    logging.exception("Google Sheet des profils inaccessible : salon profil désactivé")
    profil_sheet = None


ALLIANCE = os.getenv("ALLIANCE", "OUAF")


@tree.command(name="niveau-joueur", description="Export CSV du sheet Data OUAF : étable, champi, ouvrières")
async def niveau_joueur(interaction: discord.Interaction):
    if profil_sheet is None:
        await interaction.response.send_message("❌ Le Google Sheet n'est pas configuré. Préviens un admin.",
                                                ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        texte, avec_ids = await asyncio.to_thread(profil_sheet.export, ALLIANCE)
    except Exception:
        logging.exception("export /niveau-joueur impossible")
        await interaction.followup.send("❌ Export impossible (Google Sheet injoignable). Réessaie plus tard.",
                                        ephemeral=True)
        return
    note = "" if avec_ids else "\n⚠️ API du jeu injoignable : player_id vides, membres absents du sheet manquants."
    apercu = f"\n```csv\n{texte}```" if len(texte) < 1800 else ""     # copiable sur mobile ; limite Discord 2 000
    fichier = discord.File(io.BytesIO(texte.encode("utf-8")), filename="niveau_joueur.csv")
    await interaction.followup.send(f"📄 {texte.count(chr(10)) - 1} joueurs{note}{apercu}", file=fichier,
                                    ephemeral=True)


async def setup_hook():
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
    army = risque.army_only(message.content)
    if army:                                                   # armée seule : niveau d'Armes rentable
        await niveau_armes.ask_in_channel(message, army, armes_emojis, silent)
        return
    async with message.channel.typing():                       # le calcul prend quelques secondes
        try:
            reply = await asyncio.to_thread(risque.answer, message.content)
        except Exception:
            logging.exception("calcul impossible pour %r", message.content)
            reply = "❌ Erreur pendant le calcul. Vérifie le texte collé."
    silent = reply == risque.ENORME_TEUB or message.channel.id in SILENT_CHANNEL_IDS   # pas de notification
    await message.reply(reply, mention_author=False, silent=silent)


async def on_profil(message: discord.Message):
    try:
        values = profil.parse(message.content)
    except profil.ProfilError as e:
        await message.reply(str(e), mention_author=False, silent=True)
        return
    if profil_sheet is None:
        await message.reply("❌ Le Google Sheet n'est pas configuré. Préviens un admin.", mention_author=False, silent=True)
        return
    try:
        await asyncio.to_thread(profil_sheet.save, message.author.id, message.author.display_name, values)
    except Exception:
        logging.exception("écriture du profil impossible pour %r", message.content)
        await message.reply("❌ Pas enregistré (Google Sheet injoignable). Réessaie plus tard.", mention_author=False,
                            silent=True)
        return
    await message.reply(f"✅ Enregistré : {profil.summary(values)}", mention_author=False, silent=True)


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token or not CHANNEL_IDS:
        raise SystemExit("DISCORD_TOKEN ou CHANNEL_ID manquant : les mettre dans le fichier .env")
    client.run(token, log_handler=None)
