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

class BuffManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.init_db()

    def init_db(self):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS buffs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                buff_type TEXT,
                requested_at TEXT,
                confirmed INTEGER DEFAULT 0
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS buff_logs (
                user_id INTEGER,
                buff_type TEXT,
                used_at TEXT
            )
        """)
        conn.commit()
        conn.close()

    @app_commands.command(name="buff_request", description="Buff anfordern")
    @app_commands.describe(buff_type="Art des Buffs (training/research/building)")
    async def buff_request(self, interaction: discord.Interaction, buff_type: str):
        if buff_type not in BUFF_TYPES:
            await interaction.response.send_message("❌ Ungültiger Buff-Typ!", ephemeral=True)
            return

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO buffs (user_id, buff_type, requested_at) VALUES (?, ?, ?)",
                  (interaction.user.id, buff_type, datetime.datetime.utcnow().isoformat()))
        conn.commit()
        conn.close()

        await interaction.response.send_message(
            f"✅ Buff-Anfrage gespeichert: **{BUFF_TYPES[buff_type]['de']}**",
            ephemeral=True
        )

    @app_commands.command(name="buff_confirm", description="Buff bestätigen (Nur Buff-Giver)")
    @app_commands.describe(member="Spieler, der den Buff erhalten hat", buff_type="Art des Buffs")
    async def buff_confirm(self, interaction: discord.Interaction, member: discord.Member, buff_type: str):
        if buff_type not in BUFF_TYPES:
            await interaction.response.send_message("❌ Ungültiger Buff-Typ!", ephemeral=True)
            return

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            UPDATE buffs SET confirmed = 1
            WHERE user_id = ? AND buff_type = ? AND confirmed = 0
        """, (member.id, buff_type))
        c.execute("""
            INSERT INTO buff_logs (user_id, buff_type, used_at)
            VALUES (?, ?, ?)
        """, (member.id, buff_type, datetime.datetime.utcnow().isoformat()))
        conn.commit()
        conn.close()

        await interaction.response.send_message(
            f"✅ Buff bestätigt: **{BUFF_TYPES[buff_type]['de']}** für {member.mention}",
            ephemeral=False
        )

    @app_commands.command(name="buff_list", description="Offene Buff-Anfragen anzeigen")
    async def buff_list(self, interaction: discord.Interaction):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            SELECT user_id, buff_type, requested_at FROM buffs
            WHERE confirmed = 0
        """)
        rows = c.fetchall()
        conn.close()

        if not rows:
            await interaction.response.send_message("📭 Keine offenen Buff-Anfragen.", ephemeral=True)
            return

        embed = discord.Embed(title="📋 Offene Buff-Anfragen", color=discord.Color.orange())
        for user_id, buff_type, requested_at in rows:
            embed.add_field(
                name=f"<@{user_id}>",
                value=f"{BUFF_TYPES[buff_type]['de']} – {requested_at}",
                inline=False
            )

        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(BuffManager(bot))
