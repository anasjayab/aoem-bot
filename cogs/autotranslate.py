import os
import sqlite3
import discord
from discord.ext import commands
from discord import app_commands

DB_PATH = "aoem_bot.db"

def log(msg: str):
    print(f"[AUTOTRANS] {msg}", flush=True)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # pro Kanal: Zielsprache (de/en/es/fr)
    c.execute("""
        CREATE TABLE IF NOT EXISTS channel_lang (
            guild_id INTEGER,
            channel_id INTEGER,
            lang TEXT,
            PRIMARY KEY (guild_id, channel_id)
        )
    """)
    # Bridge: Quellkanal -> Zielkanäle für DE/EN/ES/FR
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

class AutoTranslate(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        init_db()
        self.openai_key_present = bool(os.getenv("OPENAI_API_KEY"))
        log(f"init (OPENAI_KEY={'yes' if self.openai_key_present else 'no'})")

    # ---------- Helper ----------
    def _get_lang(self, guild_id: int, channel_id: int):
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
        return row

    # ---------- Commands ----------
    @app_commands.command(name="autotranslate_show", description="Zeigt die Sprache/Bridge des aktuellen Kanals.")
    async def autotranslate_show(self, i: discord.Interaction):
        try:
            guild_id = i.guild_id
            channel_id = i.channel_id
            log(f"/autotranslate_show by {i.user.id} in {channel_id}")

            lang = self._get_lang(guild_id, channel_id)
            bridge = self._get_bridge(guild_id, channel_id)

            embed = discord.Embed(title="Auto-Translate – Status", color=discord.Color.blurple())
            embed.add_field(name="Kanal", value=f"<#{channel_id}>", inline=True)
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
                txt = "Keine Bridge für diesen Kanal."
            embed.add_field(name="Bridge-Ziele", value=txt, inline=False)

            # Hinweis zum Key, nur Info – kein Aufruf an OpenAI hier!
            embed.set_footer(text=f"OpenAI-Key erkannt: {'Ja' if self.openai_key_present else 'Nein'}")

            await i.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            log(f"ERROR in /autotranslate_show: {e}")
            await i.response.send_message("⚠️ Fehler beim Anzeigen. Siehe Logs.", ephemeral=True)

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
            conn.commit()
            conn.close()
            log(f"set lang {lang} for ch {i.channel_id}")
            await i.response.send_message(f"✅ Sprache für <#{i.channel_id}> gesetzt auf **{lang}**.", ephemeral=True)
        except Exception as e:
            log(f"ERROR in /autotranslate_set: {e}")
            await i.response.send_message("⚠️ Konnte Sprache nicht speichern.", ephemeral=True)

    @app_commands.command(name="bridge_set", description="Bridge-Ziele für DE/EN/ES/FR kanalspezifisch setzen.")
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
            conn.commit()
            conn.close()
            await i.response.send_message("✅ Bridge gespeichert.", ephemeral=True)
        except Exception as e:
            log(f"ERROR in /bridge_set: {e}")
            await i.response.send_message("⚠️ Fehler beim Speichern der Bridge.", ephemeral=True)

    @app_commands.command(name="bridge_show", description="Zeigt die Bridge-Ziele des aktuellen Kanals.")
    async def bridge_show(self, i: discord.Interaction):
        try:
            b = self._get_bridge(i.guild_id, i.channel_id)
            if not b:
                await i.response.send_message("Keine Bridge konfiguriert.", ephemeral=True)
                return
            de, en, es, fr = b
            txt = (
                f"DE → {f'<#{de}>' if de else '—'}\n"
                f"EN → {f'<#{en}>' if en else '—'}\n"
                f"ES → {f'<#{es}>' if es else '—'}\n"
                f"FR → {f'<#{fr}>' if fr else '—'}"
            )
            await i.response.send_message(txt, ephemeral=True)
        except Exception as e:
            log(f"ERROR in /bridge_show: {e}")
            await i.response.send_message("⚠️ Fehler beim Anzeigen der Bridge.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(AutoTranslate(bot))
