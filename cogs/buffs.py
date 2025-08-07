import discord, sqlite3
from discord.ext import commands
from discord import app_commands
DB_PATH="aoem.db"
def db(): c=sqlite3.connect(DB_PATH); c.execute("PRAGMA foreign_keys=ON;"); return c
def setup_tables():
    c=db()
    c.execute("""CREATE TABLE IF NOT EXISTS buffs(
      id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, name TEXT, slots INTEGER DEFAULT 5);""")
    c.execute("""CREATE TABLE IF NOT EXISTS buff_bookings(
      id INTEGER PRIMARY KEY AUTOINCREMENT, buff_id INTEGER, user_id INTEGER,
      UNIQUE(buff_id,user_id),
      FOREIGN KEY(buff_id) REFERENCES buffs(id) ON DELETE CASCADE);""")
    c.commit(); c.close()
class BuffsCog(commands.Cog):
    def __init__(self, bot): self.bot=bot; setup_tables()
    @app_commands.command(name="buff_create", description="Buff mit X Slots erstellen")
    async def buff_create(self, i:discord.Interaction, name:str, slots:int=5):
        c=db(); c.execute("INSERT INTO buffs(guild_id,name,slots) VALUES(?,?,?)",(i.guild_id,name,slots)); c.commit(); c.close()
        await i.response.send_message(f"Buff {name} mit {slots} Slots erstellt.", ephemeral=True)
    @app_commands.command(name="buff_list", description="Buffs und Belegung")
    async def buff_list(self, i:discord.Interaction):
        c=db(); cur=c.cursor(); cur.execute("SELECT id,name,slots FROM buffs WHERE guild_id=?",(i.guild_id,)); buffs=cur.fetchall()
        if not buffs: c.close(); await i.response.send_message("Keine Buffs vorhanden.",ephemeral=True); return
        lines=[]
        for bid,name,slots in buffs:
            cur.execute("SELECT COUNT(*) FROM buff_bookings WHERE buff_id=?", (bid,)); count=cur.fetchone()[0]
            lines.append(f"• {name} – {count}/{slots} belegt (ID: {bid})")
        c.close(); await i.response.send_message("\n".join(lines), ephemeral=True)
    @app_commands.command(name="buff_book", description="Slot buchen")
    async def buff_book(self, i:discord.Interaction, buff_id:int):
        c=db(); cur=c.cursor()
        cur.execute("SELECT slots FROM buffs WHERE id=? AND guild_id=?", (buff_id,i.guild_id)); row=cur.fetchone()
        if not row: c.close(); await i.response.send_message("Buff nicht gefunden.",ephemeral=True); return
        slots=row[0]; cur.execute("SELECT COUNT(*) FROM buff_bookings WHERE buff_id=?", (buff_id,)); count=cur.fetchone()[0]
        if count>=slots: c.close(); await i.response.send_message("Alle Slots belegt.",ephemeral=True); return
        try:
            cur.execute("INSERT INTO buff_bookings(buff_id,user_id) VALUES(?,?)",(buff_id,i.user.id)); c.commit()
            await i.response.send_message("Slot gebucht!",ephemeral=True)
        except sqlite3.IntegrityError:
            await i.response.send_message("Du bist bereits eingetragen.",ephemeral=True)
        finally: c.close()
    @app_commands.command(name="buff_cancel", description="Buchung stornieren")
    async def buff_cancel(self, i:discord.Interaction, buff_id:int):
        c=db(); c.execute("DELETE FROM buff_bookings WHERE buff_id=? AND user_id=?", (buff_id,i.user.id)); c.commit(); c.close()
        await i.response.send_message("Buchung storniert (falls vorhanden).",ephemeral=True)
async def setup(bot): await bot.add_cog(BuffsCog(bot))
