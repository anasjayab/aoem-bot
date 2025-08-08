# cogs/tasks.py
import os
import csv
import io
import sqlite3
from datetime import datetime, timezone
import discord
from discord.ext import commands
from discord import app_commands

DB_PATH = "aoem.db"
BOARD_CHANNEL_ID = int(os.getenv("TASK_BOARD_CHANNEL", "0"))   # optional: Kanal für Aufgaben-Posts

# ---------- DB ----------
def db():
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys = ON;")
    return con

def setup_tables():
    con = db()
    con.execute("""
    CREATE TABLE IF NOT EXISTS tasks(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        created_by INTEGER NOT NULL,
        created_ts INTEGER NOT NULL,
        due_ts INTEGER,                   -- optional UTC epoch
        status TEXT NOT NULL DEFAULT 'open',  -- open|closed
        message_id INTEGER                -- Board-Post (für Edit)
    );
    """)
    con.execute("""
    CREATE TABLE IF NOT EXISTS task_assignments(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('claimed','done','unclaimed')),
        claimed_at INTEGER,
        done_at INTEGER,
        UNIQUE(task_id, user_id),
        FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
    );
    """)
    # Aktivitätslog existiert bereits in ingame_activity.py; erweitern wir um task_*:
    con.execute("""
    CREATE TABLE IF NOT EXISTS activity_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        kind TEXT NOT NULL,           -- 'buff' | 'event' | 'task_claim' | 'task_done'
        ref_id INTEGER NOT NULL,
        member_id INTEGER NOT NULL,
        ts INTEGER NOT NULL,
        UNIQUE(kind, ref_id, member_id)
    );
    """)
    con.commit(); con.close()

def now_epoch() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp())

# ---------- UI View ----------
class TaskView(discord.ui.View):
    """Buttons sind persistent via custom_id. Funktioniert auch nach Neustart."""
    def __init__(self, task_id: int, manager_role_id: int | None = None):
        super().__init__(timeout=None)
        self.task_id = task_id
        self.manager_role_id = manager_role_id

    # --- Helpers ---
    async def _log_activity(self, guild_id: int, kind: str, ref_id: int, member_id: int):
        con = db()
        con.execute("""
            INSERT OR IGNORE INTO activity_log(guild_id, kind, ref_id, member_id, ts)
            VALUES(?,?,?,?,?)
        """, (guild_id, kind, ref_id, member_id, now_epoch()))
        con.commit(); con.close()

    async def _ensure_task_exists(self, interaction: discord.Interaction) -> tuple | None:
        con = db(); cur = con.cursor()
        cur.execute("SELECT id, title, status FROM tasks WHERE id=?", (self.task_id,))
        row = cur.fetchone(); con.close()
        if not row:
            try:
                await interaction.response.send_message("Aufgabe nicht gefunden (evtl. gelöscht).", ephemeral=True)
            except: pass
            return None
        return row

    async def _refresh_embed_on_message(self, message: discord.Message):
        # Re-build the embed from DB and edit message
        con = db(); cur = con.cursor()
        cur.execute("SELECT title, description, created_by, created_ts, due_ts, status FROM tasks WHERE id=?", (self.task_id,))
        t = cur.fetchone()
        cur.execute("""
            SELECT user_id, status FROM task_assignments WHERE task_id=?
        """, (self.task_id,))
        assigns = cur.fetchall()
        con.close()

        if not t:
            return

        title, desc, creator, cts, due_ts, status = t
        e = discord.Embed(title=f"🗒️ {title}", color=0x5865F2 if status=='open' else 0x2b2d31)
        e.add_field(name="Status", value=("🟢 offen" if status=='open' else "🔒 geschlossen"), inline=True)
        e.add_field(name="Erstellt von", value=f"<@{creator}>", inline=True)
        e.add_field(name="Erstellt", value=f"<t:{cts}:f> (UTC)", inline=True)
        if due_ts:
            e.add_field(name="Fällig bis", value=f"<t:{due_ts}:f> (UTC)", inline=True)
        if desc:
            e.add_field(name="Beschreibung", value=desc, inline=False)

        claimed = [uid for uid, st in assigns if st == 'claimed']
        done = [uid for uid, st in assigns if st == 'done']
        if claimed:
            e.add_field(name=f"Übernommen ({len(claimed)})", value=", ".join(f"<@{u}>" for u in claimed), inline=False)
        if done:
            e.add_field(name=f"Erledigt ({len(done)})", value=", ".join(f"<@{u}>" for u in done), inline=False)

        try:
            await message.edit(embed=e, view=self)
        except Exception as ex:
            print(f"[TASKS] Edit-Error: {ex}")

    # --- Buttons ---
    @discord.ui.button(label="Übernehmen", style=discord.ButtonStyle.primary, custom_id="task_claim")
    async def claim(self, interaction: discord.Interaction, _: discord.ui.Button):
        row = await self._ensure_task_exists(interaction)
        if not row: return
        task_id, title, status = row
        if status != 'open':
            await interaction.response.send_message("Diese Aufgabe ist geschlossen.", ephemeral=True); return

        con = db()
        con.execute("""
            INSERT INTO task_assignments(task_id, user_id, status, claimed_at)
            VALUES(?,?, 'claimed', ?)
            ON CONFLICT(task_id, user_id) DO UPDATE SET status='claimed', claimed_at=excluded.claimed_at
        """, (task_id, interaction.user.id, now_epoch()))
        con.commit(); con.close()

        await self._log_activity(interaction.guild_id, "task_claim", task_id, interaction.user.id)
        await interaction.response.send_message("✅ Aufgabe übernommen.", ephemeral=True)
        await self._refresh_embed_on_message(interaction.message)

    @discord.ui.button(label="Erledigt", style=discord.ButtonStyle.success, custom_id="task_done")
    async def done(self, interaction: discord.Interaction, _: discord.ui.Button):
        row = await self._ensure_task_exists(interaction)
        if not row: return
        task_id, title, status = row
        if status != 'open':
            await interaction.response.send_message("Diese Aufgabe ist geschlossen.", ephemeral=True); return

        # Nur wer sie übernommen hat, darf sie als erledigt markieren (soft rule)
        con = db(); cur = con.cursor()
        cur.execute("""
            SELECT status FROM task_assignments WHERE task_id=? AND user_id=?
        """, (task_id, interaction.user.id))
        a = cur.fetchone()
        if not a or a[0] not in ('claimed', 'done'):
            # auto-claim und dann done
            cur.execute("""
                INSERT INTO task_assignments(task_id, user_id, status, claimed_at)
                VALUES(?,?, 'claimed', ?)
                ON CONFLICT(task_id, user_id) DO UPDATE SET status='claimed'
            """, (task_id, interaction.user.id, now_epoch()))
        # setze done
        cur.execute("""
            UPDATE task_assignments SET status='done', done_at=? WHERE task_id=? AND user_id=?
        """, (now_epoch(), task_id, interaction.user.id))
        con.commit(); con.close()

        await self._log_activity(interaction.guild_id, "task_done", task_id, interaction.user.id)
        await interaction.response.send_message("🎉 Als erledigt markiert.", ephemeral=True)
        await self._refresh_embed_on_message(interaction.message)

    @discord.ui.button(label="Zurückgeben", style=discord.ButtonStyle.secondary, custom_id="task_unclaim")
    async def unclaim(self, interaction: discord.Interaction, _: discord.ui.Button):
        row = await self._ensure_task_exists(interaction)
        if not row: return
        task_id, _, status = row
        if status != 'open':
            await interaction.response.send_message("Diese Aufgabe ist geschlossen.", ephemeral=True); return
        con = db()
        con.execute("""
            INSERT OR REPLACE INTO task_assignments(task_id, user_id, status)
            VALUES(?, ?, 'unclaimed')
        """, (task_id, interaction.user.id))
        con.commit(); con.close()
        await interaction.response.send_message("↩️ Aufgabe zurückgegeben.", ephemeral=True)
        await self._refresh_embed_on_message(interaction.message)

    @discord.ui.button(label="Schließen (R4/R5)", style=discord.ButtonStyle.danger, custom_id="task_close")
    async def close(self, interaction: discord.Interaction, _: discord.ui.Button):
        # Optional: Role-Check über ENV (TASK_MANAGER_ROLE_ID)
        role_id = int(os.getenv("TASK_MANAGER_ROLE_ID", "0"))
        if role_id:
            if not any(r.id == role_id for r in getattr(interaction.user, "roles", [])):
                await interaction.response.send_message("Nur Task-Manager dürfen schließen.", ephemeral=True); return

        row = await self._ensure_task_exists(interaction)
        if not row: return
        task_id, _, status = row
        if status == 'closed':
            await interaction.response.send_message("Bereits geschlossen.", ephemeral=True); return

        con = db()
        con.execute("UPDATE tasks SET status='closed' WHERE id=?", (task_id,))
        con.commit(); con.close()
        await interaction.response.send_message("🔒 Aufgabe geschlossen.", ephemeral=True)
        await self._refresh_embed_on_message(interaction.message)

# ---------- Cog ----------
class Tasks(commands.Cog):
    """Aufgabenboard mit Buttons, CSV-Export & Activity-Integration (task_claim/task_done)."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        setup_tables()

    # -------- Commands --------
    @app_commands.command(name="task_add", description="Neue Aufgabe anlegen (optional mit Fälligkeitszeit in UTC).")
    @app_commands.describe(
        title="Kurzer Titel",
        description="Beschreibung (optional)",
        due_utc="Format: 2025-08-10 19:00 (UTC) – optional"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def task_add(self, i: discord.Interaction, title: str, description: str | None = None, due_utc: str | None = None):
        due_ts = None
        if due_utc:
            try:
                dt = datetime.strptime(due_utc, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
                due_ts = int(dt.timestamp())
            except ValueError:
                await i.response.send_message("⚠️ `due_utc` Format: `YYYY-MM-DD HH:MM` (UTC).", ephemeral=True)
                return

        # in Board-Channel posten (wenn gesetzt), sonst im aktuellen
        channel = i.guild.get_channel(BOARD_CHANNEL_ID) if BOARD_CHANNEL_ID else i.channel

        # DB: Task anlegen
        con = db()
        cur = con.cursor()
        cur.execute("""
            INSERT INTO tasks(guild_id, title, description, created_by, created_ts, due_ts)
            VALUES(?,?,?,?,?,?)
        """, (i.guild_id, title, description or "", i.user.id, now_epoch(), due_ts))
        task_id = cur.lastrowid
        con.commit(); con.close()

        # Embed + Buttons
        view = TaskView(task_id, manager_role_id=int(os.getenv("TASK_MANAGER_ROLE_ID","0")))
        msg = await channel.send(embed=self._build_embed(i.guild, task_id), view=view)

        # DB: message_id speichern
        con = db()
        con.execute("UPDATE tasks SET message_id=? WHERE id=?", (msg.id, task_id))
        con.commit(); con.close()

        await i.response.send_message(f"✅ Aufgabe erstellt (ID `{task_id}`) in {channel.mention}.", ephemeral=True)

    def _build_embed(self, guild: discord.Guild, task_id: int) -> discord.Embed:
        con = db(); cur = con.cursor()
        cur.execute("SELECT title, description, created_by, created_ts, due_ts, status FROM tasks WHERE id=?", (task_id,))
        t = cur.fetchone()
        cur.execute("SELECT user_id, status FROM task_assignments WHERE task_id=?", (task_id,))
        assigns = cur.fetchall()
        con.close()

        if not t:
            return discord.Embed(title="Aufgabe", description="(nicht gefunden)")

        title, desc, creator, cts, due_ts, status = t
        e = discord.Embed(title=f"🗒️ {title}", color=0x5865F2 if status=='open' else 0x2b2d31)
        e.add_field(name="Status", value=("🟢 offen" if status=='open' else "🔒 geschlossen"), inline=True)
        e.add_field(name="Erstellt von", value=f"<@{creator}>", inline=True)
        e.add_field(name="Erstellt", value=f"<t:{cts}:f> (UTC)", inline=True)
        if due_ts:
            e.add_field(name="Fällig bis", value=f"<t:{due_ts}:f> (UTC)", inline=True)
        if desc:
            e.add_field(name="Beschreibung", value=desc, inline=False)

        claimed = [uid for uid, st in assigns if st == 'claimed']
        done = [uid for uid, st in assigns if st == 'done']
        if claimed:
            e.add_field(name=f"Übernommen ({len(claimed)})", value=", ".join(f"<@{u}>" for u in claimed), inline=False)
        if done:
            e.add_field(name=f"Erledigt ({len(done)})", value=", ".join(f"<@{u}>" for u in done), inline=False)

        e.set_footer(text=f"Task-ID: {task_id}")
        return e

    @app_commands.command(name="task_list", description="Offene/geschlossene Aufgaben auflisten.")
    async def task_list(self, i: discord.Interaction, status: str = "open"):
        status = status.lower().strip()
        if status not in ("open", "closed"):
            await i.response.send_message("Status: `open` oder `closed`.", ephemeral=True); return
        con = db(); cur = con.cursor()
        cur.execute("""
            SELECT id, title, due_ts FROM tasks
            WHERE guild_id=? AND status=? ORDER BY COALESCE(due_ts, 9999999999), created_ts
        """, (i.guild_id, status))
        rows = cur.fetchall(); con.close()
        if not rows:
            await i.response.send_message(f"Keine {status}-Aufgaben.", ephemeral=True); return
        lines = []
        for tid, title, due_ts in rows:
            due = f" – fällig <t:{due_ts}:R>" if due_ts else ""
            lines.append(f"`{tid}` • {title}{due}")
        await i.response.send_message(("📋 Offene Aufgaben:\n" if status=='open' else "📦 Geschlossene Aufgaben:\n") + "\n".join(lines), ephemeral=True)

    @app_commands.command(name="task_close", description="Aufgabe schließen (per ID).")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def task_close(self, i: discord.Interaction, task_id: int):
        con = db(); cur = con.cursor()
        cur.execute("UPDATE tasks SET status='closed' WHERE guild_id=? AND id=?", (i.guild_id, task_id))
        changed = cur.rowcount
        cur.execute("SELECT message_id FROM tasks WHERE id=?", (task_id,))
        msgrow = cur.fetchone()
        con.commit(); con.close()

        if not changed:
            await i.response.send_message("Nicht gefunden oder schon geschlossen.", ephemeral=True); return

        await i.response.send_message("🔒 Aufgabe geschlossen.", ephemeral=True)
        # Board-Post aktualisieren
        if msgrow and msgrow[0]:
            ch = i.channel
            # versuche im Board-Channel, falls gesetzt
            if BOARD_CHANNEL_ID:
                maybe = i.guild.get_channel(BOARD_CHANNEL_ID)
                if maybe: ch = maybe
            try:
                msg = await ch.fetch_message(msgrow[0])
                # gleiche View, aber Embed neu
                view = TaskView(task_id, manager_role_id=int(os.getenv("TASK_MANAGER_ROLE_ID","0")))
                await msg.edit(embed=self._build_embed(i.guild, task_id), view=view)
            except Exception as ex:
                print(f"[TASKS] close edit err: {ex}")

    @app_commands.command(name="task_delete", description="Aufgabe löschen (per ID).")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def task_delete(self, i: discord.Interaction, task_id: int):
        con = db(); cur = con.cursor()
        # hole message_id zum Löschen
        cur.execute("SELECT message_id FROM tasks WHERE guild_id=? AND id=?", (i.guild_id, task_id))
        msgrow = cur.fetchone()
        cur.execute("DELETE FROM tasks WHERE guild_id=? AND id=?", (i.guild_id, task_id))
        deleted = cur.rowcount
        con.commit(); con.close()

        if not deleted:
            await i.response.send_message("Nicht gefunden.", ephemeral=True); return
        await i.response.send_message("🗑️ Aufgabe gelöscht.", ephemeral=True)

        # Versuche die alte Board-Nachricht zu löschen
        try:
            ch = i.guild.get_channel(BOARD_CHANNEL_ID) if BOARD_CHANNEL_ID else i.channel
            if msgrow and msgrow[0] and ch:
                msg = await ch.fetch_message(msgrow[0])
                await msg.delete()
        except: pass

    @app_commands.command(name="task_export", description="CSV-Export der Aufgaben (open/closed).")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def task_export(self, i: discord.Interaction, status: str = "open"):
        status = status.lower().strip()
        if status not in ("open","closed"):
            await i.response.send_message("Status: `open` oder `closed`.", ephemeral=True); return
        con = db(); cur = con.cursor()
        cur.execute("""
            SELECT id,title,description,created_by,created_ts,due_ts,status FROM tasks
            WHERE guild_id=? AND status=? ORDER BY created_ts
        """, (i.guild_id, status))
        rows = cur.fetchall()
        con.close()
        if not rows:
            await i.response.send_message("Keine Daten.", ephemeral=True); return

        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id","title","description","created_by","created_ts","due_ts","status"])
        w.writerows(rows)
        data = buf.getvalue().encode("utf-8")
        file = discord.File(fp=io.BytesIO(data), filename=f"tasks_{status}.csv")
        await i.response.send_message("Export:", file=file, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Tasks(bot))
