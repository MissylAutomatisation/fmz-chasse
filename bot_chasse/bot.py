"""Bot Discord « Chasse » : lit des salons dédiés (CHANNEL_ID=id1,id2) ; chaque message (armée, Armes, Bouclier, TDC) reçoit le tableau du
risque selon la taille de chasse."""
import asyncio
import logging
import os

import discord
from dotenv import load_dotenv

import niveau
import risque

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

intents = discord.Intents.default()
intents.message_content = True                                 # à activer aussi sur le portail Discord
client = discord.Client(intents=intents)
CHANNEL_IDS = {int(c) for c in os.getenv("CHANNEL_ID", "").replace(" ", "").split(",") if c}   # « id1,id2 » : un salon par serveur
SILENT_CHANNEL_IDS = {1556337362211053741}                     # réponses sans notification


@client.event
async def on_ready():
    logging.info("Connecté en tant que %s, salons %s", client.user, sorted(CHANNEL_IDS))


@client.event
async def on_message(message: discord.Message):
    if message.author.bot or message.channel.id not in CHANNEL_IDS:
        return
    if niveau.is_command(message.content):                     # « /niveau … » : rentabilité d'Armes, calcul instantané
        try:
            reply = niveau.answer(message.content)
        except Exception:
            logging.exception("calcul /niveau impossible pour %r", message.content)
            reply = "❌ Erreur pendant le calcul. Vérifie le texte collé."
        await message.reply(reply, mention_author=False, silent=message.channel.id in SILENT_CHANNEL_IDS)
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


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token or not CHANNEL_IDS:
        raise SystemExit("DISCORD_TOKEN ou CHANNEL_ID manquant : les mettre dans le fichier .env")
    client.run(token, log_handler=None)
