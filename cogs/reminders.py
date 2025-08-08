import asyncio
import sqlite3
from datetime import datetime, timedelta
import discord
from discord.ext import commands, tasks
from discord import app_commands

DB_PATH = "aoem.db"

def db():
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys = ON;")
    return con

def setup_tables():
    con = db()
    con.execute("""
    CREATE TABLE IF NOT EXISTS reminders(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        channel_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        remind_at TIMESTAMP NOT NULL
    );
    """)
    con.commit(); con.close()

class Reminders(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        setup_tables()
        self.check_reminders.start()

    def cog_unload(self):
        self.check_reminders.cancel()

    @app_commands.command(name="remind", description="Setzt eine Erinnerung.")
    @app_commands.describe(in_minutes="In wie vielen Minuten soll erinnert werden?", message="Woran soll erinnert werden?")
    async def remind(self, i: discord.Interaction, in_minutes: int, message: str):
        if in_minutes < 1:
            await i.response.send_message("Bitte mindestens 1 Minute angeben.", ephemeral=True)
            return
        remind_time = datetime.utcnow() + timedelta(minutes=in_minutes)
        con = db()
        con.execute("INSERT INTO reminders (guild_id, channel_id, user_id, message, remind_at) VALUES (?,?,?,?,?)",
                    (i.guild_id, i.channel_id, i.user.id, message, remind_time.isoformat()))
        con.commit(); con.close()
        await i.response.send_message(f"⏰ Erinnerung gesetzt für {in_minutes} Minuten: `{message}`", ephemeral=True)

    @app_commands.command(name="reminders_list", description="Listet deine gesetzten Erinnerungen.")
    async def reminders_list(self, i: discord.Interaction):
        con = db(); cur = con.cursor()
        cur.execute("SELECT id, message, remind_at FROM reminders WHERE guild_id=? AND user_id=? ORDER BY remind_at",
                    (i.guild_id, i.user.id))
        rows = cur.fetchall(); con.close()
        if not rows:
            await i.response.send_message("Du hast keine aktiven Erinnerungen.", ephemeral=True)
            return
        text = "\n".join([f"ID `{r[0]}` – `{r[1]}` um {r[2]}" for r in rows])
        await i.response.send_message(f"📋 Deine Erinnerungen:\n{text}", ephemeral=True)

    @app_commands.command(name="reminders_delete", description="Löscht eine Erinnerung per ID.")
    async def reminders_delete(self, i: discord.Interaction, reminder_id: int):
        con = db()
        cur = con.cursor()
        cur.execute("DELETE FROM reminders WHERE id=? AND user_id=?", (reminder_id, i.user.id))
        deleted = cur.rowcount
        con.commit(); con.close()
        if deleted:
            await i.response.send_message(f"🗑️ Erinnerung `{reminder_id}` gelöscht.", ephemeral=True)
        else:
            await i.response.send_message(f"Keine Erinnerung mit ID `{reminder_id}` gefunden.", ephemeral=True)

    @tasks.loop(seconds=30)
    async def check_reminders(self):
        now = datetime.utcnow()
        con = db(); cur = con.cursor()
        cur.execute("SELECT id, guild_id, channel_id, user_id, message FROM reminders WHERE remind_at <= ?", (now.isoformat(),))
        rows = cur.fetchall()
        cur.execute("DELETE FROM reminders WHERE remind_at <= ?", (now.isoformat(),))
        con.commit(); con.close()

        for r in rows:
            _id, guild_id, channel_id, user_id, message = r
            channel = self.bot.get_channel(channel_id)
            if channel:
                try:
                    await channel.send(f"⏰ <@{user_id}> Erinnerung: **{message}**")
                except Exception as e:
                    print(f"[REMINDERS] Fehler beim Senden: {e}")

    @check_reminders.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

async def setup(bot: commands.Bot):
    await bot.add_cog(Reminders(bot))
