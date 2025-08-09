import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import datetime

DB_PATH = "aoem_bot.db"

# Logging-Funktion für Buff-Nutzungen
def log_buff(user_id, buff_type):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS buff_logs (
            user_id INTEGER,
            buff_type TEXT,
            used_at TEXT
        )
    """)
    c.execute("INSERT INTO buff_logs VALUES (?, ?, ?)",
              (user_id, buff_type, datetime.datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()

class BuffManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.init_db()

    def init_db(self):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS buffs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                slots INTEGER NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS buff_bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                buff_id INTEGER,
                user_id INTEGER,
                confirmed INTEGER DEFAULT 0,
                FOREIGN KEY(buff_id) REFERENCES buffs(id)
            )
        """)
        conn.commit()
        conn.close()

    @app_commands.command(name="buff_create", description="Erstellt einen neuen Buff (Name, Slots).")
    async def buff_create(self, interaction: discord.Interaction, name: str, slots: int):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO buffs (name, slots) VALUES (?, ?)", (name, slots))
        conn.commit()
        conn.close()
        await interaction.response.send_message(f"✅ Buff **{name}** mit {slots} Slots erstellt.", ephemeral=True)

    @app_commands.command(name="buff_book", description="Bucht einen Buff-Slot.")
    async def buff_book(self, interaction: discord.Interaction, buff_name: str):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id, slots FROM buffs WHERE name = ?", (buff_name,))
        buff = c.fetchone()

        if not buff:
            await interaction.response.send_message("❌ Buff nicht gefunden.", ephemeral=True)
            return

        buff_id, slots = buff
        c.execute("SELECT COUNT(*) FROM buff_bookings WHERE buff_id = ?", (buff_id,))
        booked = c.fetchone()[0]

        if booked >= slots:
            await interaction.response.send_message("❌ Alle Slots sind bereits belegt.", ephemeral=True)
            return

        c.execute("INSERT INTO buff_bookings (buff_id, user_id) VALUES (?, ?)", (buff_id, interaction.user.id))
        conn.commit()
        conn.close()

        await interaction.response.send_message(f"✅ Du hast einen Slot für **{buff_name}** gebucht.", ephemeral=True)

    @app_commands.command(name="buff_confirm", description="Bestätigt, dass ein Buff aktiv ist.")
    async def buff_confirm(self, interaction: discord.Interaction, user: discord.Member, buff_name: str):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            SELECT bb.id FROM buff_bookings bb
            JOIN buffs b ON bb.buff_id = b.id
            WHERE bb.user_id = ? AND b.name = ?
        """, (user.id, buff_name))
        booking = c.fetchone()

        if not booking:
            await interaction.response.send_message("❌ Keine Buchung gefunden.", ephemeral=True)
            return

        c.execute("UPDATE buff_bookings SET confirmed = 1 WHERE id = ?", (booking[0],))
        conn.commit()
        conn.close()

        # Buff-Nutzung ins Log eintragen
        log_buff(user.id, buff_name)

        await interaction.response.send_message(f"✅ Buff **{buff_name}** für {user.display_name} bestätigt.")

    @app_commands.command(name="buff_list", description="Zeigt alle Buffs und Buchungen.")
    async def buff_list(self, interaction: discord.Interaction):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id, name, slots FROM buffs")
        buffs = c.fetchall()

        if not buffs:
            await interaction.response.send_message("📭 Keine Buffs vorhanden.", ephemeral=True)
            return

        embed = discord.Embed(title="📋 Buff-Liste", color=discord.Color.blue())
        for buff_id, name, slots in buffs:
            c.execute("""
                SELECT user_id, confirmed FROM buff_bookings WHERE buff_id = ?
            """, (buff_id,))
            bookings = c.fetchall()

            if bookings:
                booking_list = "\n".join(
                    f"<@{uid}> {'✅' if conf else '⌛'}" for uid, conf in bookings
                )
            else:
                booking_list = "—"

            embed.add_field(name=f"{name} ({slots} Slots)", value=booking_list, inline=False)

        conn.close()
        await interaction.response.send_message(embed=embed, ephemeral=False)

async def setup(bot):
    await bot.add_cog(BuffManager(bot))
