# cogs/activity.py
import sqlite3
from datetime import datetime, timedelta, timezone
import discord
from discord.ext import commands
from discord import app_commands

DB_PATH = "aoem.db"

def db():
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys = ON;")
    return con

def setup_tables():
    con = db()
    # Nachrichten pro Tag/Channel/User
    con.execute("""
    CREATE TABLE IF NOT EXISTS msg_counts(
        guild_id INTEGER NOT NULL,
        channel_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        day TEXT NOT NULL,           -- YYYY-MM-DD (UTC)
        count INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(guild_id, channel_id, user_id, day)
    );
    """)
    # Command-Nutzung pro Tag/Command
    con.execute("""
    CREATE TABLE IF NOT EXISTS cmd_counts(
        guild_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        day TEXT NOT NULL,
        count INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(guild_id, name, day)
    );
    """)
    # Join/Leave pro Tag
    con.execute("""
    CREATE TABLE IF NOT EXISTS joinleave(
        guild_id INTEGER NOT NULL,
        day TEXT NOT NULL,
        joins INTEGER NOT NULL DEFAULT 0,
        leaves INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(guild_id, day)
    );
    """)
    con.commit(); con.close()

def utc_day(dt=None):
    if dt is None:
        dt = datetime.now(tz=timezone.utc)
    return dt.strftime("%Y-%m-%d")

class Activity(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        setup_tables()

    # --------- Tracking ---------
    @commands.Cog.listener()
    async def on_message(self, m: discord.Message):
        if not m.guild or m.author.bot:
            return
        day = utc_day()
        con = db()
        con.execute("""
            INSERT INTO msg_counts(guild_id,channel_id,user_id,day,count)
            VALUES(?,?,?,?,1)
            ON CONFLICT(guild_id,channel_id,user_id,day)
            DO UPDATE SET count=count+1
        """, (m.guild.id, m.channel.id, m.author.id, day))
        con.commit(); con.close()

    @commands.Cog.listener()
    async def on_app_command_completion(self, interaction: discord.Interaction, command: app_commands.Command):
        if not interaction.guild:
            return
        day = utc_day()
        con = db()
        con.execute("""
            INSERT INTO cmd_counts(guild_id,name,day,count)
            VALUES(?,?,?,1)
            ON CONFLICT(guild_id,name,day) DO UPDATE SET count=count+1
        """, (interaction.guild.id, command.qualified_name, day))
        con.commit(); con.close()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        day = utc_day()
        con = db()
        con.execute("""
            INSERT INTO joinleave(guild_id,day,joins,leaves)
            VALUES(?,?,1,0)
            ON CONFLICT(guild_id,day) DO UPDATE SET joins=joins+1
        """, (member.guild.id, day))
        con.commit(); con.close()

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        day = utc_day()
        con = db()
        con.execute("""
            INSERT INTO joinleave(guild_id,day,joins,leaves)
            VALUES(?, ?,0,1)
            ON CONFLICT(guild_id,day) DO UPDATE SET leaves=leaves+1
        """, (member.guild.id, day))
        con.commit(); con.close()

    # --------- Commands ---------
    @app_commands.command(name="stats_server", description="Top Nutzer & Kanäle (letzte X Tage, Default 7).")
    async def stats_server(self, i: discord.Interaction, days: int = 7):
        await i.response.defer(ephemeral=True)
        since = (datetime.now(tz=timezone.utc) - timedelta(days=days-1)).strftime("%Y-%m-%d")
        con = db(); cur = con.cursor()

        # Top Nutzer
        cur.execute("""
            SELECT user_id, SUM(count) c FROM msg_counts
            WHERE guild_id=? AND day>=?
            GROUP BY user_id ORDER BY c DESC LIMIT 10
        """, (i.guild_id, since))
        top_users = cur.fetchall()

        # Top Kanäle
        cur.execute("""
            SELECT channel_id, SUM(count) c FROM msg_counts
            WHERE guild_id=? AND day>=?
            GROUP BY channel_id ORDER BY c DESC LIMIT 10
        """, (i.guild_id, since))
        top_channels = cur.fetchall()
        con.close()

        e = discord.Embed(title=f"📈 Server-Stats (letzte {days} Tage)", color=0x5865F2)
        if top_users:
            lines = []
            for uid, c in top_users:
                member = i.guild.get_member(uid)
                name = member.display_name if member else f"<@{uid}>"
                lines.append(f"{name}: **{c}**")
            e.add_field(name="Top Nutzer", value="\n".join(lines), inline=False)
        else:
            e.add_field(name="Top Nutzer", value="Keine Daten.", inline=False)

        if top_channels:
            lines = []
            for cid, c in top_channels:
                ch = i.guild.get_channel(cid)
                name = f"#{ch.name}" if ch else f"#{cid}"
                lines.append(f"{name}: **{c}**")
            e.add_field(name="Top Kanäle", value="\n".join(lines), inline=False)
        else:
            e.add_field(name="Top Kanäle", value="Keine Daten.", inline=False)

        await i.followup.send(embed=e, ephemeral=True)

    @app_commands.command(name="stats_channel", description="Stats für den aktuellen Kanal (letzte X Tage, Default 7).")
    async def stats_channel(self, i: discord.Interaction, days: int = 7):
        await i.response.defer(ephemeral=True)
        since = (datetime.now(tz=timezone.utc) - timedelta(days=days-1)).strftime("%Y-%m-%d")
        con = db(); cur = con.cursor()
        cur.execute("""
            SELECT user_id, SUM(count) c FROM msg_counts
            WHERE guild_id=? AND channel_id=? AND day>=?
            GROUP BY user_id ORDER BY c DESC LIMIT 10
        """, (i.guild_id, i.channel_id, since))
        rows = cur.fetchall(); con.close()

        e = discord.Embed(title=f"📊 Kanal-Stats #{i.channel.name} (letzte {days} Tage)", color=0x57F287)
        if rows:
            lines = []
            for uid, c in rows:
                member = i.guild.get_member(uid)
                name = member.display_name if member else f"<@{uid}>"
                lines.append(f"{name}: **{c}**")
            e.add_field(name="Nachrichten", value="\n".join(lines), inline=False)
        else:
            e.add_field(name="Nachrichten", value="Keine Daten.", inline=False)
        await i.followup.send(embed=e, ephemeral=True)

    @app_commands.command(name="stats_member", description="Nachrichten-Stats für ein Mitglied (letzte X Tage, Default 7).")
    async def stats_member(self, i: discord.Interaction, member: discord.Member, days: int = 7):
        await i.response.defer(ephemeral=True)
        since = (datetime.now(tz=timezone.utc) - timedelta(days=days-1)).strftime("%Y-%m-%d")
        con = db(); cur = con.cursor()
        cur.execute("""
            SELECT SUM(count) FROM msg_counts
            WHERE guild_id=? AND user_id=? AND day>=?
        """, (i.guild_id, member.id, since))
        total = cur.fetchone()[0] or 0
        con.close()

        e = discord.Embed(title=f"👤 Stats für {member.display_name}", color=0xED4245)
        e.add_field(name="Nachrichten", value=f"**{total}** in den letzten {days} Tagen", inline=False)
        await i.followup.send(embed=e, ephemeral=True)

    @app_commands.command(name="stats_joinleave", description="Join/Leave-Verlauf (letzte X Tage, Default 30).")
    async def stats_joinleave(self, i: discord.Interaction, days: int = 30):
        await i.response.defer(ephemeral=True)
        since = (datetime.now(tz=timezone.utc) - timedelta(days=days-1)).strftime("%Y-%m-%d")
        con = db(); cur = con.cursor()
        cur.execute("""
            SELECT day, joins, leaves FROM joinleave
            WHERE guild_id=? AND day>=? ORDER BY day ASC
        """, (i.guild_id, since))
        rows = cur.fetchall(); con.close()

        if not rows:
            await i.followup.send("Keine Join/Leave-Daten im Zeitraum.", ephemeral=True); return
        lines = [f"{d}: +{j}/-{l}" for d, j, l in rows]
        await i.followup.send("📅 Join/Leave:\n" + "\n".join(lines), ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Activity(bot))
