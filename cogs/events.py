import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import datetime

DB_PATH = "aoem_bot.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            description TEXT,
            start_time TEXT,
            created_by INTEGER
        )
    """)
    conn.commit()
    conn.close()

class EventManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        init_db()

    @app_commands.command(name="event_create", description="Erstelle ein Event im Kalender")
    @app_commands.describe(
        title="Titel des Events",
        description="Beschreibung (optional)",
        start_time="Startzeit im Format: DD.MM.YYYY HH:MM"
    )
    async def event_create(self, interaction: discord.Interaction, title: str, description: str = "", start_time: str = ""):
        try:
            event_dt = datetime.datetime.strptime(start_time, "%d.%m.%Y %H:%M")
        except ValueError:
            await interaction.response.send_message("⚠ Ungültiges Datumsformat! Nutze: `DD.MM.YYYY HH:MM`", ephemeral=True)
            return

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            INSERT INTO events (title, description, start_time, created_by)
            VALUES (?, ?, ?, ?)
        """, (title, description, event_dt.isoformat(), interaction.user.id))
        conn.commit()
        conn.close()

        await interaction.response.send_message(
            f"📅 Event **{title}** wurde für {event_dt.strftime('%d.%m.%Y %H:%M')} erstellt.",
            ephemeral=False
        )

    @app_commands.command(name="event_list", description="Zeigt alle kommenden Events")
    async def event_list(self, interaction: discord.Interaction):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            SELECT id, title, description, start_time FROM events
            WHERE start_time >= ?
            ORDER BY start_time ASC
        """, (datetime.datetime.utcnow().isoformat(),))
        rows = c.fetchall()
        conn.close()

        if not rows:
            await interaction.response.send_message("📭 Keine geplanten Events.", ephemeral=True)
            return

        embed = discord.Embed(title="📅 Kommende Events", color=discord.Color.green())
        for eid, title, desc, ts in rows:
            ts_str = datetime.datetime.fromisoformat(ts).strftime("%d.%m.%Y %H:%M")
            embed.add_field(name=f"ID {eid} – {title}", value=f"{desc or 'Keine Beschreibung'}\n🕒 {ts_str}", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="event_delete", description="Lösche ein Event")
    async def event_delete(self, interaction: discord.Interaction, event_id: int):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM events WHERE id=?", (event_id,))
        conn.commit()
        conn.close()

        await interaction.response.send_message(f"🗑 Event mit ID {event_id} wurde gelöscht.", ephemeral=False)

async def setup(bot):
    await bot.add_cog(EventManager(bot))
