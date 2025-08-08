import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import datetime

DB_PATH = "aoem_bot.db"

BUFF_TYPES = {
    "training": {"de": "Trainingsbeschleunigung", "en": "Training Speedup", "fr": "Accélération d'entraînement", "es": "Aceleración de entrenamiento"},
    "research": {"de": "Forschungsbeschleunigung", "en": "Research Speedup", "fr": "Accélération de recherche", "es": "Aceleración de investigación"},
    "building": {"de": "Baubeschleunigung", "en": "Building Speedup", "fr": "Accélération de construction", "es": "Aceleración de construcción"}
}

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS buffs_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            buff_type TEXT,
            requested_at TEXT,
            confirmed_by INTEGER,
            confirmed_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS buffs_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            buff_type TEXT,
            confirmed_at TEXT
        )
    """)
    conn.commit()
    conn.close()

class BuffManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        init_db()

    @app_commands.command(name="buff_request", description="Fordere einen Buff an")
    @app_commands.describe(buff_type="training / research / building", lang="Sprache für Buff-Namen")
    async def buff_request(self, interaction: discord.Interaction, buff_type: str, lang: str = "de"):
        if buff_type not in BUFF_TYPES:
            await interaction.response.send_message("⚠ Ungültiger Buff-Typ", ephemeral=True)
            return
        if lang not in ["de", "en", "fr", "es"]:
            lang = "de"

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO buffs_requests (user_id, buff_type, requested_at) VALUES (?, ?, ?)",
                  (interaction.user.id, buff_type, datetime.datetime.utcnow().isoformat()))
        conn.commit()
        conn.close()

        buff_name = BUFF_TYPES[buff_type][lang]
        await interaction.response.send_message(
            f"📢 {interaction.user.mention} hat **{buff_name}** angefordert.\nBuff-Giver bitte bestätigen mit `/buff_confirm`.",
            ephemeral=False
        )

    @app_commands.command(name="buff_confirm", description="Bestätige, dass ein Buff gegeben wurde")
    @app_commands.describe(request_id="ID der Buff-Anfrage")
    async def buff_confirm(self, interaction: discord.Interaction, request_id: int):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT user_id, buff_type FROM buffs_requests WHERE id=? AND confirmed_by IS NULL", (request_id,))
        row = c.fetchone()
        if not row:
            await interaction.response.send_message("⚠ Anfrage nicht gefunden oder schon bestätigt.", ephemeral=True)
            conn.close()
            return

        user_id, buff_type = row
        c.execute("""
            UPDATE buffs_requests
            SET confirmed_by=?, confirmed_at=?
            WHERE id=?
        """, (interaction.user.id, datetime.datetime.utcnow().isoformat(), request_id))
        c.execute("""
            INSERT INTO buffs_usage (user_id, buff_type, confirmed_at)
            VALUES (?, ?, ?)
        """, (user_id, buff_type, datetime.datetime.utcnow().isoformat()))
        conn.commit()
        conn.close()

        await interaction.response.send_message(
            f"✅ Buff **{BUFF_TYPES[buff_type]['de']}** wurde für <@{user_id}> bestätigt.",
            ephemeral=False
        )

    @app_commands.command(name="buff_list", description="Zeigt offene Buff-Anfragen")
    async def buff_list(self, interaction: discord.Interaction):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            SELECT id, user_id, buff_type, requested_at
            FROM buffs_requests
            WHERE confirmed_by IS NULL
        """)
        rows = c.fetchall()
        conn.close()

        if not rows:
            await interaction.response.send_message("📭 Keine offenen Buff-Anfragen.", ephemeral=True)
            return

        embed = discord.Embed(title="📋 Offene Buff-Anfragen", color=discord.Color.blue())
        for rid, uid, btype, ts in rows:
            ts_str = datetime.datetime.fromisoformat(ts).strftime("%d.%m %H:%M")
            embed.add_field(name=f"ID {rid} – {BUFF_TYPES[btype]['de']}", value=f"<@{uid}> – {ts_str}", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=False)

async def setup(bot):
    await bot.add_cog(BuffManager(bot))
