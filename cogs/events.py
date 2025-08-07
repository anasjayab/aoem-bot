import discord, sqlite3
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timezone
DB_PATH="aoem.db"
def db(): 
    c=sqlite3.connect(DB_PATH); c.execute("PRAGMA foreign_keys=ON;"); return c
def setup_tables():
    c=db()
    c.execute("""CREATE TABLE IF NOT EXISTS events(
      id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, channel_id INTEGER,
      message_id INTEGER, title TEXT, start_ts INTEGER);""")
    c.execute("""CREATE TABLE IF NOT EXISTS rsvps(
      id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER, user_id INTEGER,
      status TEXT CHECK(status IN ('yes','maybe','no')),
      UNIQUE(event_id,user_id),
      FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE);""")
    c.commit(); c.close()
async def set_rsvp(eid, uid, status):
    c=db(); c.execute(
      "INSERT INTO rsvps(event_id,user_id,status) VALUES(?,?,?) "
      "ON CONFLICT(event_id,user_id) DO UPDATE SET status=excluded.status;",
      (eid,uid,status)); c.commit(); c.close()
class RSVPButtons(discord.ui.View):
    def __init__(self, eid:int): super().__init__(timeout=None); self.eid=eid
    @discord.ui.button(label="Beitreten", style=discord.ButtonStyle.success, custom_id="rsvp_yes")
    async def yes(self,i,b): await set_rsvp(self.eid,i.user.id,"yes"); await i.response.send_message("Eingetragen: Ja",ephemeral=True)
    @discord.ui.button(label="Vielleicht", style=discord.ButtonStyle.secondary, custom_id="rsvp_maybe")
    async def maybe(self,i,b): await set_rsvp(self.eid,i.user.id,"maybe"); await i.response.send_message("Eingetragen: Vielleicht",ephemeral=True)
    @discord.ui.button(label="Absagen", style=discord.ButtonStyle.danger, custom_id="rsvp_no")
    async def no(self,i,b): await set_rsvp(self.eid,i.user.id,"no"); await i.response.send_message("Eingetragen: Nein",ephemeral=True)
class EventsCog(commands.Cog):
    def __init__(self, bot): self.bot=bot; setup_tables()
    @app_commands.command(name="event_create", description="Event mit Join-Buttons erstellen")
    @app_commands.describe(title="Titel", start_utc="UTC-Zeit: 2025-08-08 18:00")
    async def event_create(self, i:discord.Interaction, title:str, start_utc:str):
        try: dt=datetime.strptime(start_utc,"%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        except ValueError: 
            await i.response.send_message("Format: YYYY-MM-DD HH:MM (UTC).", ephemeral=True); return
        c=db(); cur=c.cursor()
        cur.execute("INSERT INTO events(guild_id,channel_id,title,start_ts) VALUES(?,?,?,?)",
                    (i.guild_id,i.channel_id,title,int(dt.timestamp()))); eid=cur.lastrowid
        c.commit(); c.close()
        emb=discord.Embed(title=title, description=f"Start (UTC): **{dt:%Y-%m-%d %H:%M}**", color=0x2b2d31)
        emb.set_footer(text=f"Event-ID: {eid}")
        view=RSVPButtons(eid); msg=await i.channel.send(embed=emb, view=view)
        c=db(); c.execute("UPDATE events SET message_id=? WHERE id=?",(msg.id,eid)); c.commit(); c.close()
        await i.response.send_message(f"Event erstellt (ID: {eid})", ephemeral=True)
    @app_commands.command(name="event_list", description="Kommende Events zeigen")
    async def event_list(self, i:discord.Interaction):
        c=db(); cur=c.cursor()
        cur.execute("SELECT id,title,start_ts FROM events WHERE guild_id=? ORDER BY start_ts ASC LIMIT 10",(i.guild_id,))
        rows=cur.fetchall(); c.close()
        if not rows: await i.response.send_message("Keine Events gefunden.",ephemeral=True); return
        out=[f"• {t} – {datetime.fromtimestamp(ts,tz=timezone.utc):%Y-%m-%d %H:%M} UTC (ID: {eid})" for eid,t,ts in rows]
        await i.response.send_message("\n".join(out),ephemeral=True)
async def setup(bot): await bot.add_cog(EventsCog(bot))
