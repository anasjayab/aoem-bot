import os, re, sqlite3, requests, discord
from discord.ext import commands
from discord import app_commands

DB_PATH = "aoem.db"
SUPPORTED = ["de", "en", "es", "fr"]

def db():
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys = ON;")
    return con

def setup_tables():
    con = db()
    con.execute("""
    CREATE TABLE IF NOT EXISTS lang_bridges(
        guild_id INTEGER PRIMARY KEY,
        de_channel_id INTEGER,
        en_channel_id INTEGER,
        es_channel_id INTEGER,
        fr_channel_id INTEGER
    );
    """)
    con.commit(); con.close()

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def _translate(text: str, target: str) -> str:
    """DeepL wenn DEEPL_KEY gesetzt, sonst LibreTranslate (ohne Key)."""
    text = text.strip()
    if not text:
        return text

    key = os.getenv("DEEPL_KEY")
    if key:
        # DeepL
        url = "https://api-free.deepl.com/v2/translate"
        data = {"auth_key": key, "text": text, "target_lang": target.upper()}
        r = requests.post(url, data=data, timeout=12)
        r.raise_for_status()
        return r.json()["translations"][0]["text"]

    # Fallback: LibreTranslate (kann rate-limiten)
    url = "https://libretranslate.com/translate"
    data = {"q": text, "source": "auto", "target": target, "format": "text"}
    r = requests.post(url, data=data, timeout=12)
    r.raise_for_status()
    return r.json().get("translatedText", text)

class BridgeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        setup_tables()
        self._tag = "[AOEM-BRIDGE]"  # Loop-Breaker

    @app_commands.command(name="bridge_set", description="Setzt DE/EN/ES/FR-Zielkanäle.")
    @app_commands.describe(de="Deutsch-Kanal", en="Englisch-Kanal", es="Spanisch-Kanal", fr="Französisch-Kanal")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def bridge_set(self, i: discord.Interaction,
                         de: discord.TextChannel, en: discord.TextChannel,
                         es: discord.TextChannel, fr: discord.TextChannel):
        con = db()
        con.execute("""
        INSERT INTO lang_bridges(guild_id,de_channel_id,en_channel_id,es_channel_id,fr_channel_id)
        VALUES(?,?,?,?,?)
        ON CONFLICT(guild_id) DO UPDATE SET
            de_channel_id=excluded.de_channel_id,
            en_channel_id=excluded.en_channel_id,
            es_channel_id=excluded.es_channel_id,
            fr_channel_id=excluded.fr_channel_id
        """, (i.guild_id, de.id, en.id, es.id, fr.id))
        con.commit(); con.close()
        await i.response.send_message(
            f"✅ Gesetzt:\nDE {de.mention}\nEN {en.mention}\nES {es.mention}\nFR {fr.mention}",
            ephemeral=True
        )

    @app_commands.command(name="bridge_show", description="Zeigt die gespeicherten Sprachkanäle.")
    async def bridge_show(self, i: discord.Interaction):
        con = db(); cur = con.cursor()
        cur.execute("SELECT de_channel_id,en_channel_id,es_channel_id,fr_channel_id FROM lang_bridges WHERE guild_id=?",
                    (i.guild_id,))
        row = cur.fetchone(); con.close()
        if not row:
            await i.response.send_message("Noch keine Brücke gesetzt. Nutze `/bridge_set`.", ephemeral=True); return
        de_id, en_id, es_id, fr_id = row
        def m(cid):
            ch = i.guild.get_channel(cid)
            return ch.mention if ch else f"`#{cid}`"
        await i.response.send_message(f"DE {m(de_id)} | EN {m(en_id)} | ES {m(es_id)} | FR {m(fr_id)}", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, msg: discord.Message):
        if not msg.guild or msg.author.bot:
            return
        if self._tag in (msg.content or ""):
            return

        con = db(); cur = con.cursor()
        cur.execute("SELECT de_channel_id,en_channel_id,es_channel_id,fr_channel_id FROM lang_bridges WHERE guild_id=?",
                    (msg.guild.id,))
        row = cur.fetchone(); con.close()
        if not row:
            return

        de_id, en_id, es_id, fr_id = row
        mapping = {"de": de_id, "en": en_id, "es": es_id, "fr": fr_id}

        # Quelle bestimmen
        src_lang = next((l for l, cid in mapping.items() if cid and msg.channel.id == cid), None)
        if not src_lang:
            return

        content = _norm(msg.content)
        if not content:
            return

        author = msg.author.display_name
        src_info = f"{author} in #{msg.channel.name}"

        # In andere Sprachen spiegeln
        for lang, cid in mapping.items():
            if not cid or lang == src_lang:
                continue
            try:
                translated = _translate(content, lang)
            except Exception as e:
                translated = f"(Übersetzung fehlgeschlagen: {e})\n{content}"
            ch = msg.guild.get_channel(cid)
            if not ch:
                continue
            out = (
                f"{self._tag} **{src_info} → {lang.upper()}**\n"
                f"{translated}\n"
                f"— Original: {content}"
            )
            await ch.send(out, allowed_mentions=discord.AllowedMentions.none())

async def setup(bot: commands.Bot):
    await bot.add_cog(BridgeCog(bot))
