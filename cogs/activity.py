import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import datetime

DB_PATH = "aoem_bot.db"

class ActivityReport(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="activity_report", description="Zeigt Buff-Nutzungen im gewählten Zeitraum")
    @app_commands.describe(days="Zeitraum in Tagen (Standard: 7)")
    async def activity_report(self, interaction: discord.Interaction, days: int = 7):
        """Buff-Nutzungen im gewählten Zeitraum anzeigen."""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        since_date = datetime.datetime.utcnow() - datetime.timedelta(days=days)

        # Events auslesen
        c.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                start_time TEXT
            )
        """)
        c.execute("SELECT id, title, start_time FROM events WHERE start_time >= ?", (since_date.isoformat(),))
        events = c.fetchall()

        # Buff-Nutzungen auslesen
        c.execute("""
            CREATE TABLE IF NOT EXISTS buff_logs (
                user_id INTEGER,
                buff_type TEXT,
                used_at TEXT
            )
        """)
        c.execute("SELECT user_id, buff_type, used_at FROM buff_logs WHERE used_at >= ?", (since_date.isoformat(),))
        buff_logs = c.fetchall()
        conn.close()

        if not buff_logs:
            await interaction.response.send_message("📭 Keine Buff-Nutzungen im angegebenen Zeitraum.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"📊 Activity Report – Letzte {days} Tage",
            color=discord.Color.blue()
        )

        # Events + Buffs zusammenführen
        for event_id, title, start_time in events:
            event_dt = datetime.datetime.fromisoformat(start_time)
            related_buffs = [
                log for log in buff_logs
                if abs((datetime.datetime.fromisoformat(log[2]) - event_dt).total_seconds()) <= 3 * 3600
            ]
            if related_buffs:
                buff_info = "\n".join(
                    f"<@{user_id}> – {buff_type} ({used_at})"
                    for user_id, buff_type, used_at in related_buffs
                )
                embed.add_field(
                    name=f"📅 {title} ({event_dt.strftime('%d.%m.%Y %H:%M UTC')})",
                    value=buff_info,
                    inline=False
                )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="activity_user", description="Zeigt Buff-Historie eines Spielers")
    async def activity_user(self, interaction: discord.Interaction, member: discord.Member, days: int = 30):
        """Zeigt Buff-Nutzungen eines Spielers im gewählten Zeitraum."""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        since_date = datetime.datetime.utcnow() - datetime.timedelta(days=days)
        c.execute("""
            SELECT buff_type, used_at FROM buff_logs
            WHERE user_id = ? AND used_at >= ?
            ORDER BY used_at DESC
        """, (member.id, since_date.isoformat()))
        logs = c.fetchall()
        conn.close()

        if not logs:
            await interaction.response.send_message(f"📭 Keine Buff-Nutzungen für {member.display_name} gefunden.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"📜 Buff-Historie – {member.display_name} (Letzte {days} Tage)",
            color=discord.Color.green()
        )
        for buff_type, used_at in logs:
            embed.add_field(
                name=buff_type,
                value=datetime.datetime.fromisoformat(used_at).strftime("%d.%m.%Y %H:%M UTC"),
                inline=False
            )

        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(ActivityReport(bot))
