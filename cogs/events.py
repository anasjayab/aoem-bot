# cogs/events.py
import discord
from discord.ext import commands, tasks
from discord import app_commands
import sqlite3
from datetime import datetime, timedelta
import os

DB_PATH = "events.db"
EVENT_CHANNEL_ID = int(os.getenv("EVENT_CHANNEL_ID", 0))  # Standard-Kanal für Erinnerungen
EVENT_MANAGER_ROLE_ID = int(os.getenv("EVENT_MANAGER_ROLE_ID", 0))  # z. B. R4/R5
REMINDER_MINUTES = int(os.getenv("REMINDER_MINUTES", 15))  # Vorlaufzeit in Minuten

# Templates für häufige Events
EVENT_TEMPLATES = {
    "kvk_training": "Königreichskrieg – Training Day",
    "allianzfest": "Allianzfest",
    "bau_buffs": "Bau-Buffs Tag"
}

class EventManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.conn = sqlite3.connect(DB_PATH)
        self.create_table()
        self.reminder_loop.start()

    def create_table(self):
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    description TEXT,
                    event_time TEXT,
                    reminded INTEGER DEFAULT 0
                )
            """)

    def add_event(self, name, description, event_time):
        with self.conn:
            self.conn.execute(
                "INSERT INTO events (name, description, event_time) VALUES (?, ?, ?)",
                (name, description, event_time)
            )

    def get_upcoming_events(self):
        now = datetime.utcnow()
        with self.conn:
            return self.conn.execute(
                "SELECT id, name, description, event_time FROM events WHERE datetime(event_time) > ? ORDER BY event_time ASC",
                (now.strftime("%Y-%m-%d %H:%M:%S"),)
            ).fetchall()

    def mark_reminded(self, event_id):
        with self.conn:
            self.conn.execute("UPDATE events SET reminded = 1 WHERE id = ?", (event_id,))

    @app_commands.command(name="event_add", description="Füge ein neues Event hinzu")
    @app_commands.describe(
        template="Name eines Templates (optional)",
        name="Name des Events (wenn kein Template gewählt)",
        description="Kurze Beschreibung",
        date="Datum im Format JJJJ-MM-TT",
        time="Uhrzeit im Format HH:MM (Serverzeit)"
    )
    async def event_add(self, interaction: discord.Interaction, template: str = None, name: str = None, description: str = None, date: str = None, time: str = None):
        # Rollenprüfung
        if EVENT_MANAGER_ROLE_ID != 0:
            role = discord.utils.get(interaction.guild.roles, id=EVENT_MANAGER_ROLE_ID)
            if role not in interaction.user.roles:
                await interaction.response.send_message("❌ Du hast keine Berechtigung, Events zu erstellen.", ephemeral=True)
                return

        # Template-Namen einsetzen
        if template and template in EVENT_TEMPLATES:
            event_name = EVENT_TEMPLATES[template]
        elif name:
            event_name = name
        else:
            await interaction.response.send_message("❌ Du musst entweder ein Template oder einen Namen angeben.", ephemeral=True)
            return

        if not date or not time:
            await interaction.response.send_message("❌ Bitte Datum und Uhrzeit angeben.", ephemeral=True)
            return

        try:
            event_dt = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
        except ValueError:
            await interaction.response.send_message("❌ Falsches Datums- oder Zeitformat.", ephemeral=True)
            return

        self.add_event(event_name, description or "", event_dt.strftime("%Y-%m-%d %H:%M:%S"))
        await interaction.response.send_message(f"✅ Event **{event_name}** am {date} um {time} Uhr gespeichert.", ephemeral=True)

    @app_commands.command(name="event_list", description="Zeigt alle kommenden Events")
    async def event_list(self, interaction: discord.Interaction):
        events = self.get_upcoming_events()
        if not events:
            await interaction.response.send_message("📭 Keine kommenden Events.", ephemeral=True)
            return

        embed = discord.Embed(title="📅 Kommende Events", color=discord.Color.blue())
        for e in events:
            dt = datetime.strptime(e[3], "%Y-%m-%d %H:%M:%S")
            embed.add_field(
                name=f"{dt.strftime('%d.%m. %H:%M')} – {e[1]}",
                value=e[2] or "Keine Beschreibung",
                inline=False
            )
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @tasks.loop(minutes=1)
    async def reminder_loop(self):
        now = datetime.utcnow()
        events = self.get_upcoming_events()
        for e in events:
            event_id, name, desc, event_time = e
            event_dt = datetime.strptime(event_time, "%Y-%m-%d %H:%M:%S")
            if not self.already_reminded(event_id) and now >= event_dt - timedelta(minutes=REMINDER_MINUTES):
                channel = self.bot.get_channel(EVENT_CHANNEL_ID)
                if channel:
                    await channel.send(f"⏰ **Erinnerung:** {name} startet in {REMINDER_MINUTES} Minuten!\n{desc or ''}")
                self.mark_reminded(event_id)

    def already_reminded(self, event_id):
        with self.conn:
            result = self.conn.execute("SELECT reminded FROM events WHERE id = ?", (event_id,)).fetchone()
            return result and result[0] == 1

async def setup(bot):
    await bot.add_cog(EventManager(bot))
