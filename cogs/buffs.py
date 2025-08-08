# cogs/buffs.py
import os
import sqlite3
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands, tasks
from discord import app_commands

DB_PATH = "aoem.db"

# ---------- ENV: IDs als Strings/Zahlen erlaubt ----------
REQ_CH_ID = int(os.getenv("BUFF_REQUEST_CHANNEL", "0"))     # Kanal für Anfragen/Posts mit Buttons
LOG_CH_ID = int(os.getenv("BUFF_LOG_CHANNEL", "0"))         # Kanal für Log/History/Reminder
OVW_CH_ID = int(os.getenv("BUFF_OVERVIEW_CHANNEL", "0"))    # Kanal für Übersicht (Tabelle)
GIVER_ROLE_ID = int(os.getenv("BUFF_GIVER_ROLE_ID", "0"))   # Discord-Rolle, die bestätigen darf
REM_LEAD_MIN = int(os.getenv("BUFF_REMINDER_LEAD_MIN", "5"))  # Minuten vor Start erinnern

# ---------- Buff-Übersetzungen ----------
BUFF_NAMES = {
    "training": {"de": "Trainingsbeschleunigung", "en": "Training Speed", "es": "Aceleración de entrenamiento", "fr": "Accélération d'entraînement"},
    "research": {"de": "Forschungsbeschleunigung", "en": "Research Speed", "es": "Aceleración de investigación", "fr": "Accélération de recherche"},
    "build":    {"de": "Baubeschleunigung",        "en": "Building Speed", "es": "Aceleración de construcción",  "fr": "Accélération de construction"},
}
LANG_FALLBACK = "de"

def buff_label(kind: str, lang: str) -> str:
    lang = (lang or LANG_FALLBACK).lower()
    return BUFF_NAMES.get(kind, {}).get(lang, BUFF_NAMES.get(kind, {}).get(LANG_FALLBACK, kind))

# ---------- DB-Helpers ----------
def db():
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys = ON;")
    return con

def setup_tables():
    con = db()
    con.execute("""
    CREATE TABLE IF NOT EXISTS buff_requests(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        channel_id INTEGER NOT NULL,   -- wo die Anfrage-Embed steht
        message_id INTEGER,            -- Embed-Nachricht
        creator_id INTEGER NOT NULL,
        buff_type TEXT NOT NULL,       -- training|research|build
        lang TEXT NOT NULL DEFAULT 'de',
        start_ts INTEGER NOT NULL,     -- UTC epoch seconds
        confirmed_by INTEGER,          -- user id der bestätigt hat
        confirmed_at INTEGER,          -- epoch seconds
        reminder_sent INTEGER NOT NULL DEFAULT 0,
        started_sent INTEGER NOT NULL DEFAULT 0
    );
    """)
    con.execute("""
    CREATE TABLE IF NOT EXISTS buff_participants(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('yes','maybe','no')),
        UNIQUE(request_id, user_id),
        FOREIGN KEY(request_id) REFERENCES buff_requests(id) ON DELETE CASCADE
    );
    """)
    con.execute("""
    CREATE TABLE IF NOT EXISTS buff_overview(
        guild_id INTEGER PRIMARY KEY,
        message_id INTEGER
    );
    """)
    con.commit()
    con.close()

# ---------- UI ----------
class RSVPView(discord.ui.View):
    def __init__(self, request_id: int, giver_role_id: int):
        super().__init__(timeout=None)
        self.request_id = request_id
        self.giver_role_id = giver_role_id

    async def _set_status(self, interaction: discord.Interaction, status: str):
        con = db()
        con.execute(
            "INSERT INTO buff_participants(request_id,user_id,status) VALUES(?,?,?) "
            "ON CONFLICT(request_id,user_id) DO UPDATE SET status=excluded.status",
            (self.request_id, interaction.user.id, status)
        )
        con.commit(); con.close()
        await interaction.response.send_message(
            f"Dein Status ist jetzt: **{'Ja' if status=='yes' else 'Vielleicht' if status=='maybe' else 'Nein'}**",
            ephemeral=True
        )

    @discord.ui.button(label="Beitreten", style=discord.ButtonStyle.success, custom_id="buff_yes")
    async def join(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._set_status(interaction, "yes")

    @discord.ui.button(label="Vielleicht", style=discord.ButtonStyle.secondary, custom_id="buff_maybe")
    async def maybe(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._set_status(interaction, "maybe")

    @discord.ui.button(label="Absagen", style=discord.ButtonStyle.danger, custom_id="buff_no")
    async def decline(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._set_status(interaction, "no")

    @discord.ui.button(label="Bestätigen (Buff Giver)", style=discord.ButtonStyle.primary, custom_id="buff_confirm")
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button):
        # Rollen-Check
        if self.giver_role_id:
            has_role = any(r.id == self.giver_role_id for r in getattr(interaction.user, "roles", []))
            if not has_role:
                await interaction.response.send_message("Nur **Buff Giver** können bestätigen.", ephemeral=True)
                return

        now = int(datetime.now(tz=timezone.utc).timestamp())
        con = db()
        con.execute(
            "UPDATE buff_requests SET confirmed_by=?, confirmed_at=? WHERE id=?",
            (interaction.user.id, now, self.request_id)
        )
        con.commit(); con.close()
        await interaction.response.send_message("✅ Buff **bestätigt**. Erinnerungen werden geplant.", ephemeral=True)

# ---------- Cog ----------
class Buffs(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        setup_tables()
        self.reminder_loop.start()

    def cog_unload(self):
        self.reminder_loop.cancel()

    # ---- Slash: Buff anfragen ----
    @app_commands.command(name="buff_request", description="Fordere einen Buff an (mit Uhrzeit in UTC).")
    @app_commands.choices(buff=[
        app_commands.Choice(name="Trainingsbeschleunigung", value="training"),
        app_commands.Choice(name="Forschungsbeschleunigung", value="research"),
        app_commands.Choice(name="Baubeschleunigung", value="build"),
    ])
    @app_commands.describe(
        buff="Buff-Typ",
        start_utc="Start in UTC: 2025-08-08 18:00",
        lang="Sprache für Anzeige/Erinnerungen (de/en/es/fr)"
    )
    async def buff_request(self, i: discord.Interaction, buff: app_commands.Choice[str], start_utc: str, lang: str = LANG_FALLBACK):
        # Zeit parsen
        try:
            dt = datetime.strptime(start_utc, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        except ValueError:
            await i.response.send_message("⚠️ Format: `YYYY-MM-DD HH:MM` (UTC). Beispiel: `2025-08-08 18:00`", ephemeral=True)
            return

        # In Request-Kanal posten (falls gesetzt), sonst im aktuellen Kanal
        channel = i.guild.get_channel(REQ_CH_ID) if REQ_CH_ID else i.channel

        # DB: Request speichern
        con = db()
        cur = con.cursor()
        cur.execute("""
            INSERT INTO buff_requests(guild_id, channel_id, creator_id, buff_type, lang, start_ts)
            VALUES(?,?,?,?,?,?)
        """, (i.guild_id, channel.id, i.user.id, buff.value, lang.lower(), int(dt.timestamp())))
        req_id = cur.lastrowid
        con.commit(); con.close()

        # Embed + Buttons
        emb = await self._build_request_embed(i.guild, req_id)
        view = RSVPView(req_id, GIVER_ROLE_ID)
        msg = await channel.send(embed=emb, view=view)

        # DB: message_id updaten
        con = db()
        con.execute("UPDATE buff_requests SET message_id=? WHERE id=?", (msg.id, req_id))
        con.commit(); con.close()

        # Log
        if LOG_CH_ID:
            log_ch = i.guild.get_channel(LOG_CH_ID)
            if log_ch:
                lbl = buff_label(buff.value, lang)
                await log_ch.send(f"📝 **Buff-Anfrage**: {i.user.mention} → **{lbl}** um **{dt:%Y-%m-%d %H:%M} UTC** (ID `{req_id}`)")

        # Antwort
        await i.response.send_message(f"Buff-Anfrage erstellt (ID `{req_id}`) in {channel.mention}.", ephemeral=True)

        # Übersicht aktualisieren
        await self._refresh_overview(i.guild)

    # ---- Slash: Liste/Übersicht neu posten (falls nötig) ----
    @app_commands.command(name="buff_overview", description="Aktualisiert die Übersicht im OVW-Kanal.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def buff_overview(self, i: discord.Interaction):
        await self._refresh_overview(i.guild)
        await i.response.send_message("Übersicht aktualisiert.", ephemeral=True)

    # ---------- Helper: Embed bauen ----------
    async def _build_request_embed(self, guild: discord.Guild, request_id: int) -> discord.Embed:
        con = db(); cur = con.cursor()
        cur.execute("SELECT buff_type, lang, start_ts, creator_id, confirmed_by FROM buff_requests WHERE id=?", (request_id,))
        row = cur.fetchone()
        if not row:
            con.close()
            return discord.Embed(title="Buff", description="(nicht gefunden)")
        buff_type, lang, ts, creator_id, confirmed_by = row
        cur.execute("SELECT user_id, status FROM buff_participants WHERE request_id=?", (request_id,))
        parts = cur.fetchall()
        con.close()

        yes = [u for (u,s) in parts if s == "yes"]
        maybe = [u for (u,s) in parts if s == "maybe"]
        no = [u for (u,s) in parts if s == "no"]

        lbl = buff_label(buff_type, lang)
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)

        emb = discord.Embed(title=f"📣 {lbl}", color=0x2b2d31)
        emb.add_field(name="Start (UTC)", value=f"**{dt:%Y-%m-%d %H:%M}**", inline=True)
        emb.add_field(name="Status", value=("✅ Bestätigt" if confirmed_by else "⏳ Wartet auf Bestätigung"), inline=True)
        emb.add_field(name="Erstellt von", value=f"<@{creator_id}>", inline=True)
        def mentions(ids): 
            return ", ".join(f"<@{x}>" for x in ids) if ids else "—"
        emb.add_field(name=f"Teilnehmer ({len(yes)})", value=mentions(yes), inline=False)
        emb.add_field(name=f"Vielleicht ({len(maybe)})", value=mentions(maybe), inline=False)
        if no:
            emb.add_field(name=f"Abgesagt ({len(no)})", value=mentions(no), inline=False)
        emb.set_footer(text=f"Request-ID: {request_id}")
        return emb

    # ---------- Helper: Übersicht ----------
    async def _refresh_overview(self, guild: discord.Guild):
        if not OVW_CH_ID:
            return
        ch = guild.get_channel(OVW_CH_ID)
        if not ch:
            return
        # liest kommende Requests (nächste 30)
        now = int(datetime.now(tz=timezone.utc).timestamp())
        con = db(); cur = con.cursor()
        cur.execute("""
            SELECT id, buff_type, lang, start_ts
            FROM buff_requests
            WHERE guild_id=? AND start_ts >= ?
            ORDER BY start_ts ASC
            LIMIT 30
        """, (guild.id, now))
        rows = cur.fetchall()
        cur.execute("SELECT message_id FROM buff_overview WHERE guild_id=?", (guild.id,))
        ovw = cur.fetchone()
        con.close()

        lines = []
        for rid, btype, lang, ts in rows:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            lines.append(f"• **{dt:%Y-%m-%d %H:%M} UTC** – {buff_label(btype, lang)} (ID `{rid}`)")

        txt = "\n".join(lines) if lines else "Keine kommenden Buffs."
        content = f"📊 **Buff-Übersicht**\n{txt}"

        try:
            if ovw and ovw[0]:
                # versuche existierende Übersicht zu editieren
                msg = await ch.fetch_message(ovw[0])
                await msg.edit(content=content)
            else:
                msg = await ch.send(content)
                # speichern
                con = db()
                con.execute("INSERT OR REPLACE INTO buff_overview(guild_id, message_id) VALUES(?,?)", (guild.id, msg.id))
                con.commit(); con.close()
        except discord.NotFound:
            # neu posten, falls Msg weg
            msg = await ch.send(content)
            con = db()
            con.execute("INSERT OR REPLACE INTO buff_overview(guild_id, message_id) VALUES(?,?)", (guild.id, msg.id))
            con.commit(); con.close()
        except Exception as e:
            print(f"[BUFF_OVERVIEW] Fehler: {e}")

    # ---------- Loop: Erinnerungen & Start ----------
    @tasks.loop(seconds=30)
    async def reminder_loop(self):
        now = datetime.now(tz=timezone.utc)
        lead_cutoff = int((now + timedelta(minutes=REM_LEAD_MIN)).timestamp())
        now_epoch = int(now.timestamp())

        con = db(); cur = con.cursor()
        # 1) Erinnerungen vor Start (nur wenn bestätigt, reminder_sent=0, und Start in <= lead)
        cur.execute("""
            SELECT id, guild_id FROM buff_requests
            WHERE confirmed_by IS NOT NULL
              AND reminder_sent = 0
              AND start_ts <= ?
              AND start_ts > ?
        """, (lead_cutoff, now_epoch))
        to_remind = cur.fetchall()

        # 2) Start-Meldung (wenn Start vorbei, started_sent=0)
        cur.execute("""
            SELECT id, guild_id FROM buff_requests
            WHERE confirmed_by IS NOT NULL
              AND started_sent = 0
              AND start_ts <= ?
        """, (now_epoch,))
        to_start = cur.fetchall()
        con.close()

        # Erinnerungen verschicken
        for req_id, guild_id in to_remind:
            await self._send_reminder(guild_id, req_id, kind="reminder")
            con = db()
            con.execute("UPDATE buff_requests SET reminder_sent=1 WHERE id=?", (req_id,))
            con.commit(); con.close()

        # Start verschicken
        for req_id, guild_id in to_start:
            await self._send_reminder(guild_id, req_id, kind="start")
            con = db()
            con.execute("UPDATE buff_requests SET started_sent=1 WHERE id=?", (req_id,))
            con.commit(); con.close()

    @reminder_loop.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()

    async def _send_reminder(self, guild_id: int, request_id: int, kind: str):
        """kind: 'reminder' (vorab) oder 'start' (Startzeit erreicht)."""
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
        # Request & Teilnehmer
        con = db(); cur = con.cursor()
        cur.execute("SELECT buff_type, lang, start_ts, confirmed_by FROM buff_requests WHERE id=?", (request_id,))
        row = cur.fetchone()
        if not row:
            con.close(); return
        btype, lang, ts, confirmed_by = row
        cur.execute("SELECT user_id FROM buff_participants WHERE request_id=? AND status='yes'", (request_id,))
        yes = [u for (u,) in cur.fetchall()]
        con.close()

        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        lbl = buff_label(btype, lang)

        # Zielkanal für Info
        log_ch = guild.get_channel(LOG_CH_ID) if LOG_CH_ID else None
        text = "🔔 Erinnerung" if kind == "reminder" else "🚀 Start"
        msg = f"{text}: **{lbl}** um **{dt:%Y-%m-%d %H:%M} UTC**"
        if confirmed_by:
            msg += f" • bestätigt von <@{confirmed_by}>"

        # 1) DM an Teilnehmer (best effort)
        for uid in yes:
            member = guild.get_member(uid)
            if not member:
                continue
            try:
                await member.send(f"{text} auf **{guild.name}**: {lbl} um {dt:%Y-%m-%d %H:%M} UTC")
            except:
                # DM gescheitert – ignorieren
                pass

        # 2) Log-Channel Nachricht
        if log_ch:
            try:
                # auch Teilnehmer erwähnen, aber ohne Everyone/Here
                mentions = " ".join(f"<@{u}>" for u in yes) if yes else ""
                await log_ch.send(f"{msg}\n{mentions}", allowed_mentions=discord.AllowedMentions(users=True, everyone=False, roles=False))
            except Exception as e:
                print(f"[BUFF_LOG] Fehler beim Senden: {e}")

    # ---------- Message-Update beim Interagieren ----------
    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """Wenn Buttons geklickt wurden, versuche die zugehörige Embed zu aktualisieren."""
        try:
            if not interaction.message or not interaction.message.embeds:
                return
        except AttributeError:
            return

        # Versuche, anhand der Footer-ID die Request zu erkennen
        emb = interaction.message.embeds[0]
        if not emb.footer or not emb.footer.text or "Request-ID:" not in emb.footer.text:
            return
        try:
            req_id = int(emb.footer.text.split("Request-ID:")[-1].strip())
        except:
            return

        # Embed neu bauen & editieren
        new_emb = await self._build_request_embed(interaction.guild, req_id)
        try:
            await interaction.message.edit(embed=new_emb, view=interaction.message.components and interaction.message.components[0])
        except:
            # Notfalls ohne View (Buttons bleiben trotzdem durch persistent custom_id funktionsfähig)
            try:
                await interaction.message.edit(embed=new_emb)
            except Exception as e:
                print(f"[BUFF_UPDATE] Fehler: {e}")

        # Übersicht updaten
        try:
            await self._refresh_overview(interaction.guild)
        except:
            pass

async def setup(bot: commands.Bot):
    await bot.add_cog(Buffs(bot))
