import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import datetime

DB_PATH = "aoem_bot.db"

class ActivityReport(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def fetch_data(self, start_date):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Buff-Nutzung
        c.execute("""
            SELECT user_id, buff_type, confirmed_at
            FROM buffs_usage
            WHERE confirmed_at >= ?
        """, (start_date.isoformat(),))
        buffs = c.fetchall()

        # Warplan-Teilnahmen
        c.execute("""
            SELECT wp.title, wpp.user_id, wpp.status
            FROM warplan_participants wpp
            JOIN warplans wp ON wp.id = wpp.plan_id
            WHERE wp.start_time >= ?
        """, (start_date.isoformat(),))
        warplans = c.fetchall()

        # Event-Teilnahmen
        c.execute("""
            SELECT e.title, ep.user_id, ep.status
            FROM event_participants ep
            JOIN events e ON e.id = ep.event_id
            WHERE e.start_time >= ?
        """, (start_date.isoformat(),))
        events = c.fetchall()

        conn.close()
        return buffs, warplans, events

    def format_report(self, buffs, warplans, events):
        report = "**📊 Aktivitäts-Report**\n\n"

        report += "__Buff-Nutzung:__\n"
        if buffs:
            for uid, buff_type, ts in buffs:
                date_str = datetime.datetime.fromisoformat(ts).strftime("%d.%m %H:%M")
                report += f"<@{uid}> – {buff_type} ({date_str})\n"
        else:
            report += "Keine Buffs genutzt.\n"

        report += "\n__Warplans:__\n"
        if warplans:
            for title, uid, status in warplans:
                report += f"<@{uid}> – {title} ({status})\n"
        else:
            report += "Keine Kriegspläne.\n"

        report += "\n__Events:__\n"
        if events:
            for title, uid, status in events:
                report += f"<@{uid}> – {title} ({status})\n"
        else:
            report += "Keine Events.\n"

        return report

    @app_commands.command(name="activity_report", description="Zeigt Aktivitätsdaten")
    @app_commands.describe(period="Zeitraum: week oder month")
    async def activity_report(self, interaction: discord.Interaction, period: str):
        now = datetime.datetime.utcnow()
        if period == "week":
            start_date = now - datetime.timedelta(days=7)
        elif period == "month":
            start_date = now.replace(day=1)
        else:
            await interaction.response.send_message("⚠ Ungültiger Zeitraum. Nutze: week oder month", ephemeral=True)
            return

        buffs, warplans, events = self.fetch_data(start_date)
        report_text = self.format_report(buffs, warplans, events)

        await interaction.response.send_message(report_text, ephemeral=True)

async def setup(bot):
    await bot.add_cog(ActivityReport(bot))
