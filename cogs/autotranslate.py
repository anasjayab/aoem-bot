import os, re, sqlite3, requests, discord
from discord.ext import commands
from discord import app_commands

DB_PATH = "aoem.db"
TAG = "[AOEM-AT]"  # Loop-Breaker

def db():
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys = ON;")
    return con

def setup_tables():
    con = db()
    con.execute("""
    CREATE TABLE IF NOT EXISTS autotranslate_channels(
        guild_id INTEGER NOT NULL,
        channel_id INTEGER NOT NULL,
        target_lang TEXT NOT NULL,
        PRIMARY KEY(guild_id, channel_id)
    );
    """)
    con.commit(); con.close()

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def _translate(text: str, target: str) -> str:
    """DeepL (wenn DEEPL_KEY gesetzt), sonst LibreTranslate."""
    text = text.strip()
    if not text:
        return text

    key = os.getenv("DEEPL_KEY")
    if key:
        url = "https://api-free.deepl.com/v2/translate"
        data = {"auth_key": key, "text": text, "target_lang": target.upper()}
        r = requests.post(url, data=data, timeout=12); r.raise_for_status()
        return r.json()["translations"][0]["text"]

    url = "https://libretranslate.com/translate"
    data = {"q": text, "source": "auto", "target": target, "format": "text"}
    r = requests.post(url, data=data, timeout=12); r.raise_for_status()
    return r.json().get("translatedText", text)

class AutoTranslate(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        setup_tables()

    @app_commands.command(name="autotranslate", description="Automatische Übersetzung im aktuellen Kanal an/aus.")
    @app_commands.describe(mode="on/off", to="Zielsprache, z.B. en, de, es, fr")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def autotranslate(self, i: discord.Interaction, mode: str, to: str | None = None):
        mode = mode.lower().strip()
        if mode not in ("on", "off"):
            await i.response.send_message("Nutze: `/autotranslate mode:on to:en` oder `/autotranslate mode:off`.", ephemeral=True); return

        if mode == "on":
            if not to:
                await i.response.send_message("Bitte Zielsprache angeben, z. B. `en`, `de`, `es`, `fr`.", ephemeral=True); return
            to = to.lower().strip()
            if len(to) not in (2, 3):
                await i.response.send_message("Ungültiger Sprachcode. Beispiel: `en`, `de`, `es`, `fr`.", ephemeral=True); return
            con = db()
            con.execute("INSERT OR REPLACE INTO autotranslate_channels(guild_id, channel_id, target_lang) VALUES(?,?,?)",
                        (i.guild_id, i.channel_id, to))
            con.commit(); con.close()
            await i.response.send_message(f"✅ Auto-Übersetzung **aktiv**: -> `{to}` in <#{i.channel_id}>", ephemeral=True)
        else:
            con = db()
            con.execute("DELETE FROM autotranslate_channels WHERE guild_id=? AND channel_id=?", (i.guild_id, i.channel_id))
            con.commit(); con.close()
            await i.response.send_message(f"⏹️ Auto-Übersetzung **deaktiviert** in <#{i.channel_id}>.", ephemeral=True)

    @app_commands.command(name="autotranslate_show", description="Zeigt die Zielsprache des aktuellen Kanals.")
    async def autotranslate_show(self, i: discord.Interaction):
        con = db(); cur = con.cursor()
        cur.execute("SELECT target_lang FROM autotranslate_channels WHERE guild_id=? AND channel_id=?", (i.guild_id, i.channel_id))
        row = cur.fetchone(); con.close()
        if not row:
            await i.response.send_message("In diesem Kanal ist Auto-Übersetzung **aus**.", ephemeral=True); return
        await i.response.send_message(f"In diesem Kanal ist Auto-Übersetzung **an** → `{row[0]}`.", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, m: discord.Message):
        if not m.guild or m.author.bot:
            return
        if TAG in (m.content or ""):
            return

        con = db(); cur = con.cursor()
        cur.execute("SELECT target_lang FROM autotranslate_channels WHERE guild_id=? AND channel_id=?", (m.guild.id, m.channel.id))
        row = cur.fetchone(); con.close()
        if not row:
            return
        target = (row[0] or "").strip().lower()
        content = _norm(m.content)
        if not content:
            return

        try:
            translated = _translate(content, target)
        except Exception as e:
            translated = f"(Übersetzung fehlgeschlagen: {e})\n{content}"

        out = f"{TAG} {translated}\n— Original: {content}"
        await m.channel.send(out, allowed_mentions=discord.AllowedMentions.none())

async def setup(bot: commands.Bot):
    await bot.add_cog(AutoTranslate(bot))
