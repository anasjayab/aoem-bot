import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import datetime

DB_PATH = "aoem_bot.db"

class ActivityReport(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="activity_report", description="Zeigt Buff-Nutzungen in Bezug auf Events")
    async def activity_report(self, interaction: discord.Interaction, days: int = 7):
        """Erstellt einen Bericht der Buff-Nutzungen im angegebenen Zeitraum."""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        since_date = datetime.datetime.utcnow() - datetime.timedelta(days=days)

        # Events laden
        c.execute("""
            SELECT id, title, start_time FROM events
            WHERE start_time >= ?
            ORDER BY start_time ASC
        """, (since_date.isoformat(),))
        events = c.fetchall()

        # Buff-Nutzungen laden
        c.execute("""
            SELECT user_id, buff_type, used_at FROM buff_logs
            WHERE used_at >= ?
            ORDER BY used_at ASC
        """, (since_date.isoformat(),))
        buff_logs = c.fetchall()
        conn.close()

        if not buff_logs:
            await interaction.response.send_message("📭 Keine Buff-Nutzungen im angegebenen Zeitraum.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"📊 Activity Report – Letzte {days} Tage",
            description="Buff-Nutzungen im Zusammenhang mit Events",
            color=discord.Color.blue()
        )

        for event_id, title, start_time in events:
            event_dt = datetime.datetime.fromisoformat(start_time)
            related_buffs = [
                log for log in buff_logs
                if abs((datetime.datetime.fromisoformat(log[2]) - event_dt).total_seconds()) <= 3600 * 3
            ]
            if related_buffs:
                buff_info = "\n".join(
                    f"<@{user_id}> – {buff_type} ({used_at})"
                    for user_id, buff_type, used_at in related_buffs
                )
                embed.add_field(
                    name=f"📅 {title} ({event_dt.strftime('%d.%m.%Y %H:%M')})",
                    value=buff_info,
                    inline=False
                )

        await interaction.response.send_message(embed=embed, ephemeral=False)

async def setup(bot):
    await bot.add_cog(ActivityReport(bot))
