import os
import sqlite3
import requests
import discord
from discord.ext import commands
from discord import app_commands

DB_PATH = "aoem_bot.db"
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

LANG_NAMES = {"de": "German", "en": "English", "es": "Spanish", "fr": "French"}

def log(msg: str):
    print(f"[AUTOTRANS] {msg}", flush=True)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
      CREATE TABLE IF NOT EXISTS channel_lang (
        guild_id INTEGER,
        channel_id INTEGER,
        lang TEXT,
        PRIMARY KEY (guild_id, channel_id)
      )
    """)
    c.execute("""
      CREATE TABLE IF NOT EXISTS bridges (
        guild_id INTEGER,
        source_channel_id INTEGER PRIMARY KEY,
        de_channel_id INTEGER,
        en_channel_id INTEGER,
        es_channel_id INTEGER,
        fr_channel_id INTEGER
      )
    """)
    conn.commit()
    conn.close()

# ---------------- OpenAI helper ----------------
def translate_text(text: str, target_lang: str) -> str | None:
    """Translate text to target_lang using OpenAI. Returns translated text or None on error."""
    if not OPENAI_KEY:
        log("No OPENAI_API_KEY set - skipping translate.")
        return None
    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o-mini",
                "temperature": 0,
                "messages": [
                    {
                        "role": "system",
                        "content": f"You are a translator. Translate the user's message into {LANG_NAMES[target_lang]}. "
                                   f"Output only the translation with no extra text, no quotes, no emojis."
                    },
                    {"role": "user", "content": text}
                ],
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log(f"translate error: {e}")
        return None

class AutoTranslate(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        init_db()
        log(f"init (OPENAI_KEY={'yes' if bool(OPENAI_KEY) else 'no'})")

    # ---------- DB helpers ----------
    def _get_lang(self, guild_id: int, channel_id: int) -> str | None:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT lang FROM channel_lang WHERE guild_id=? AND channel_id=?", (guild_id, channel_id))
        row = c.fetchone()
        conn.close()
        return row[0] if row else None

    def _get_bridge(self, guild_id: int, source_channel_id: int):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
          SELECT de_channel_id, en_channel_id, es_channel_id, fr_channel_id
          FROM bridges WHERE guild_id=? AND source_channel_id=?
        """, (guild_id, source_channel_id))
        row = c.fetchone()
        conn.close()
        return row  # tuple or None

    # ---------- Slash commands ----------
    @app_commands.command(name="autotranslate_set", description="Setzt die Sprache des aktuellen Kanals (de/en/es/fr).")
    async def autotranslate_set(self, i: discord.Interaction, lang: str):
        lang = lang.lower()
        if lang not in ("de", "en", "es", "fr"):
            await i.response.send_message("Erlaubt: de, en, es, fr.", ephemeral=True)
            return
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("""
              INSERT INTO channel_lang (guild_id, channel_id, lang)
              VALUES (?, ?, ?)
              ON CONFLICT(guild_id, channel_id) DO UPDATE SET lang=excluded.lang
            """, (i.guild_id, i.channel_id, lang))
            conn.commit(); conn.close()
            log(f"set lang {lang} for ch {i.channel_id}")
            await i.response.send_message(f"✅ Sprache für <#{i.channel_id}> gesetzt auf **{lang}**.", ephemeral=True)
        except Exception as e:
            log(f"ERROR /autotranslate_set: {e}")
            await i.response.send_message("⚠️ Konnte Sprache nicht speichern.", ephemeral=True)

    @app_commands.command(name="autotranslate_show", description="Zeigt Sprache & Bridge des aktuellen Kanals.")
    async def autotranslate_show(self, i: discord.Interaction):
        try:
            lang = self._get_lang(i.guild_id, i.channel_id)
            bridge = self._get_bridge(i.guild_id, i.channel_id)
            embed = discord.Embed(title="Auto-Translate – Status", color=discord.Color.blurple())
            embed.add_field(name="Kanal", value=f"<#{i.channel_id}>", inline=True)
            embed.add_field(name="Sprache", value=lang or "— (nicht gesetzt)", inline=True)
            if bridge:
                de, en, es, fr = bridge
                txt = (
                    f"DE → {f'<#{de}>' if de else '—'}\n"
                    f"EN → {f'<#{en}>' if en else '—'}\n"
                    f"ES → {f'<#{es}>' if es else '—'}\n"
                    f"FR → {f'<#{fr}>' if fr else '—'}"
                )
            else:
                txt = "Keine Bridge konfiguriert."
            embed.add_field(name="Bridge-Ziele", value=txt, inline=False)
            embed.set_footer(text=f"OpenAI-Key erkannt: {'Ja' if OPENAI_KEY else 'Nein'}")
            await i.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            log(f"ERROR /autotranslate_show: {e}")
            await i.response.send_message("⚠️ Fehler beim Anzeigen. Siehe Logs.", ephemeral=True)

    @app_commands.command(name="bridge_set", description="Setzt Bridge: DE/EN/ES/FR Zielkanäle für diesen Kanal.")
    async def bridge_set(
        self,
        i: discord.Interaction,
        de: discord.TextChannel | None = None,
        en: discord.TextChannel | None = None,
        es: discord.TextChannel | None = None,
        fr: discord.TextChannel | None = None,
    ):
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("""
              INSERT INTO bridges (guild_id, source_channel_id, de_channel_id, en_channel_id, es_channel_id, fr_channel_id)
              VALUES (?, ?, ?, ?, ?, ?)
              ON CONFLICT(source_channel_id) DO UPDATE SET
                de_channel_id=excluded.de_channel_id,
                en_channel_id=excluded.en_channel_id,
                es_channel_id=excluded.es_channel_id,
                fr_channel_id=excluded.fr_channel_id
            """, (i.guild_id, i.channel_id,
                  de.id if de else None,
                  en.id if en else None,
                  es.id if es else None,
                  fr.id if fr else None))
            conn.commit(); conn.close()
            await i.response.send_message("✅ Bridge gespeichert.", ephemeral=True)
        except Exception as e:
            log(f"ERROR /bridge_set: {e}")
            await i.response.send_message("⚠️ Fehler beim Speichern der Bridge.", ephemeral=True)

    @app_commands.command(name="bridge_show", description="Zeigt Bridge-Ziele dieses Kanals.")
    async def bridge_show(self, i: discord.Interaction):
        try:
            b = self._get_bridge(i.guild_id, i.channel_id)
            if not b:
                await i.response.send_message("Keine Bridge konfiguriert.", ephemeral=True); return
            de, en, es, fr = b
            txt = (
                f"DE → {f'<#{de}>' if de else '—'}\n"
                f"EN → {f'<#{en}>' if en else '—'}\n"
                f"ES → {f'<#{es}>' if es else '—'}\n"
                f"FR → {f'<#{fr}>' if fr else '—'}"
            )
            await i.response.send_message(txt, ephemeral=True)
        except Exception as e:
            log(f"ERROR /bridge_show: {e}")
            await i.response.send_message("⚠️ Fehler beim Anzeigen der Bridge.", ephemeral=True)

    # ---------- Listener: translate & forward ----------
    @commands.Cog.listener("on_message")
    async def on_message(self, msg: discord.Message):
        try:
            if msg.author.bot or not msg.guild or not msg.content:
                return

            guild_id = msg.guild.id
            source_ch = msg.channel.id
            source_lang = self._get_lang(guild_id, source_ch)
            bridge = self._get_bridge(guild_id, source_ch)

            # Nur arbeiten, wenn Bridge existiert
            if not bridge:
                return

            de_ch, en_ch, es_ch, fr_ch = bridge
            targets = {"de": de_ch, "en": en_ch, "es": es_ch, "fr": fr_ch}

            # Standard-Quelle unbekannt? Dann trotzdem in alle gesetzten Ziele übersetzen
            for lang, ch_id in targets.items():
                if not ch_id:
                    continue
                # nicht in Kanal übersetzen, der schon diese Sprache ist
                if source_lang and source_lang == lang:
                    continue

                translated = translate_text(msg.content, lang)
                if not translated:
                    continue

                channel: discord.TextChannel = msg.guild.get_channel(ch_id)
                if not channel:
                    continue

                # kurze, saubere Ausgabe
                text = f"**{msg.author.display_name}:** {translated}"
                await channel.send(text)
        except Exception as e:
            log(f"ERROR on_message: {e}")

async def setup(bot):
    await bot.add_cog(AutoTranslate(bot))
