import os, sys, asyncio, importlib, traceback
import discord
from discord.ext import commands
from dotenv import load_dotenv

# ---- .env / ENV ----
load_dotenv()
TOKEN = os.getenv("TOKEN")
GUILD_LIMIT = os.getenv("APPROVED_GUILDS", "").strip()  # optional Allowlist, kommasepariert

# ---- Intents ----
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

# ---- Bot-Klasse ----
class AoEMBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=commands.when_mentioned_or("!"),
            intents=intents,
            help_command=None,
            application_id=os.getenv("APPLICATION_ID") and int(os.getenv("APPLICATION_ID")) or None
        )

    async def setup_hook(self):
        # Auto-Load aller .py im cogs/ Ordner
        loaded, failed = [], []
        if not os.path.isdir("cogs"):
            os.makedirs("cogs", exist_ok=True)
        for fname in os.listdir("cogs"):
            if not fname.endswith(".py") or fname.startswith(("_", "__")):
                continue
            mod = f"cogs.{fname[:-3]}"
            try:
                await self.load_extension(mod)
                loaded.append(mod)
            except Exception:
                failed.append((mod, traceback.format_exc()))
        print(f"[COGS] Loaded: {loaded}")
        if failed:
            print("[COGS] Failed:")
            for mod, err in failed:
                print(f" - {mod}\n{err}")

        # Slash-Commands sync
        try:
            await self.tree.sync()
            print("Slash commands synced.")
        except Exception as e:
            print("Slash sync error:", e)

bot = AoEMBot()

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="AoE:M – /help"))
    # Optional Allowlist (verlässt fremde Server automatisch)
    if GUILD_LIMIT:
        allowed = {int(x) for x in GUILD_LIMIT.split(",") if x.strip().isdigit()}
        for g in list(bot.guilds):
            if g.id not in allowed:
                print(f"[GUARD] Leaving not-allowed guild: {g.name} ({g.id})")
                try: await g.leave()
                except: pass

# Minimal /help
@bot.tree.command(name="help", description="Kurzüberblick der wichtigsten Befehle.")
async def help_cmd(i: discord.Interaction):
    txt = (
        "**AoE:M Bot – Kurzbefehle**\n"
        "• `/buff_request`, `/buff_confirm`, `/buff_list`\n"
        "• `/event_create`, `/event_list`, `/event_delete`\n"
        "• `/activity_report`, `/activity_user`\n"
        "• `/autotranslate`, `/autotranslate_show`\n"
        "• `/task_add`, `/task_list`, `/task_close`, `/task_delete`, `/task_export`\n"
        "• `/warplan_create`\n"
    )
    await i.response.send_message(txt, ephemeral=True)

if __name__ == "__main__":
    # Keep-Alive Webserver (Render Free wachhalten)
    try:
        from keepalive import keepalive
        keepalive()
    except Exception as e:
        print("[KEEPALIVE] skipped:", e)

    if not TOKEN:
        print("ERROR: TOKEN fehlt in ENV/.env")
        sys.exit(1)
    bot.run(TOKEN)
