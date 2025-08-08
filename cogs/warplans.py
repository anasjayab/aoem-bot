import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import View, Button
import sqlite3
import datetime
import asyncio

DB_PATH = "aoem_bot.db"

class WarPlanView(View):
    def __init__(self, plan_id):
        super().__init__(timeout=None)
        self.plan_id = plan_id

    @discord.ui.button(label="✅ Bestätigt", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: Button):
        self.update_participant(interaction.user.id, "confirmed")
        await interaction.response.send_message("Du hast die Teilnahme bestätigt ✅", ephemeral=True)

    @discord.ui.button(label="❓ Frage", style=discord.ButtonStyle.secondary)
    async def question(self, interaction: discord.Interaction, button: Button):
        self.update_participant(interaction.user.id, "question")
        await interaction.response.send_message("Deine Teilnahme ist als 'Frage' markiert ❓", ephemeral=True)

    @discord.ui.button(label="❌ Abgemeldet", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: Button):
        self.update_participant(interaction.user.id, "declined")
        await interaction.response.send_message("Du hast dich vom Plan abgemeldet ❌", ephemeral=True)

    def update_participant(self, user_id, status):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO warplan_participants (plan_id, user_id, status) VALUES (?, ?, ?)",
                  (self.plan_id, user_id, status))
        conn.commit()
        conn.close()


class WarPlans(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_reminders.start()
        self.init_db()

    def init_db(self):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS warplans (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT,
                        description TEXT,
                        start_time TEXT,
                        channel_id INTEGER,
                        message_id INTEGER
                    )""")
        c.execute("""CREATE TABLE IF NOT EXISTS warplan_participants (
                        plan_id INTEGER,
                        user_id INTEGER,
                        status TEXT,
                        PRIMARY KEY (plan_id, user_id)
                    )""")
        conn.commit()
        conn.close()

    @app_commands.command(name="warplan_create", description="Erstellt einen neuen Kriegsplan")
    @app_commands.describe(title="Titel des Plans", description="Beschreibung", start_time="Startzeit (YYYY-MM-DD HH:MM, 24h)")
    async def warplan_create(self, interaction: discord.Interaction, title: str, description: str, start_time: str):
        try:
            start_dt = datetime.datetime.strptime(start_time, "%Y-%m-%d %H:%M")
        except ValueError:
            await interaction.response.send_message("⚠ Ungültiges Zeitformat. Benutze: YYYY-MM-DD HH:MM", ephemeral=True)
            return

        embed = discord.Embed(title=f"🛡 Kriegplan: {title}", description=description, color=discord.Color.red())
        embed.add_field(name="Startzeit", value=start_dt.strftime("%d.%m.%Y %H:%M Uhr"))
        embed.set_footer(text="Bestätige deine Teilnahme mit den Buttons unten.")

        msg = await interaction.channel.send(embed=embed, view=WarPlanView(plan_id=0))  # temp ID

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO warplans (title, description, start_time, channel_id, message_id) VALUES (?, ?, ?, ?, ?)",
                  (title, description, start_dt.isoformat(), interaction.channel.id, msg.id))
        plan_id = c.lastrowid
        conn.commit()
        conn.close()

        # Update view with real plan_id
        await msg.edit(view=WarPlanView(plan_id=plan_id))
        await interaction.response.send_message(f"✅ Kriegsplan '{title}' erstellt!", ephemeral=True)

    @tasks.loop(minutes=1)
    async def check_reminders(self):
        now = datetime.datetime.utcnow()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id, title, start_time, channel_id, message_id FROM warplans")
        for plan_id, title, start_time, channel_id, message_id in c.fetchall():
            start_dt = datetime.datetime.fromisoformat(start_time)
            diff = (start_dt - now).total_seconds()
            if diff in (1800, 300):  # 30 Min oder 5 Min vorher
                channel = self.bot.get_channel(channel_id)
                if channel:
                    msg = await channel.fetch_message(message_id)
                    await channel.send(f"⚔ Erinnerung: **{title}** startet bald! Bitte bereit machen!")
        conn.close()

async def setup(bot):
    await bot.add_cog(WarPlans(bot))
