"""Bot Discord « Chasse » : lit des salons dédiés (CHANNEL_ID=id1,id2) ; chaque message (armée, Armes, Bouclier, TDC) reçoit le tableau du
risque selon la taille de chasse."""
import asyncio
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
PROFIL_CHANNEL_ID = 1560005265061974087                        # ov, Champignonnière, Étable -> Google Sheet
try:
    profil_sheet = profil.from_env()
except Exception:
    logging.exception("Google Sheet des profils inaccessible : salon profil désactivé")
    profil_sheet = None


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
    if message.channel.id == PROFIL_CHANNEL_ID:
        await on_profil(message)
        return
    if message.channel.id not in CHANNEL_IDS:
        return
    async with message.channel.typing():                       # le calcul prend quelques secondes
        try:
            reply = await asyncio.to_thread(risque.answer, message.content, False)    # le tableau d'abord, vite
        except Exception:
            logging.exception("calcul impossible pour %r", message.content)
            reply = "❌ Erreur pendant le calcul. Vérifie le texte collé."
    silent = reply == risque.ENORME_TEUB or message.channel.id in SILENT_CHANNEL_IDS   # pas de notification
    sent = await message.reply(reply, mention_author=False, silent=silent)
    if risque.WAIT_PLAN not in reply:
        return
    try:                                                       # puis les prochaines chasses (le cache garde le tableau)
        full = await asyncio.to_thread(risque.answer, message.content)
    except Exception:
        logging.exception("prochaines chasses impossibles pour %r", message.content)
        full = reply.replace(risque.WAIT_PLAN, "📅 Prochaines chasses : calcul impossible.")
    await sent.edit(content=full)


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
