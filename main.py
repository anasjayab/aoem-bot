import os, discord
from discord.ext import commands
from dotenv import load_dotenv
from keepalive import keepalive

load_dotenv(); TOKEN = os.getenv("TOKEN")
intents = discord.Intents.default()
intents.message_content = intents.members = intents.presences = True

class AoEMBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=commands.when_mentioned_or("!"), intents=intents)
    async def setup_hook(self):
        await self.load_extension("cogs.events")
        await self.load_extension("cogs.buffs")
        await self.tree.sync(); print("Slash commands synced.")

bot = AoEMBot()

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="AoE:M | /help"))

@bot.tree.command(name="ping", description="Teste, ob der Bot antwortet.")
async def ping(i: discord.Interaction): await i.response.send_message("Pong!", ephemeral=True)

@bot.tree.command(name="help", description="Kurzübersicht der wichtigsten Befehle.")
async def help_cmd(i: discord.Interaction):
    await i.response.send_message("Befehle: /ping • /event_create • /event_list • /buff_create • /buff_list • /buff_book • /buff_cancel", ephemeral=True)

if __name__ == "__main__":
    keepalive()
    if not TOKEN: raise RuntimeError("Setze TOKEN als Variable.")
    bot.run(TOKEN)
