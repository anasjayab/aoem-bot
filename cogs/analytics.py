# cogs/analytics.py
import sqlite3
from datetime import datetime, timedelta, timezone
import re
import discord
from discord.ext import commands
from discord import app_commands

AOE_DB = "aoem.db"     # Buffs & activity
EVT_DB = "events.db"   # Events (aus cogs/events.py)

CATEGORIES = ["kvk", "mge", "other"]  # frei erweiterbar

# ------------------- DB Helpers -------------------
def db(path):
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys = ON;")
    return con

def setup_tables():
    # Meta zu Events in events.db
    con = db(EVT_DB)
    con.execute("""
    CREATE TABLE IF NOT EXISTS event_meta(
        event_id INTEGER PRIMARY KEY,
        category TEXT,            -- kvk|mge|other (frei)
        duration_min INTEGER      -- Dauerfenster für Overlap
    );
    """)
    con.commit(); con.close()

def utc(dt: datetime):
    return dt.astimezone(timezone.utc)

def parse_dt(s: str) -> datetime:
    # erwartet "%Y-%m-%d %H:%M:%S" (so speichert events.py)
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)

# naive Keyword-Heuristik, falls keine Meta hinterlegt ist
KEYWORDS = {
    "kvk": [r"kvk", r"kingdom.*war", r"kriegs?"],
    "mge": [r"\bmge\b", r"might.*event", r"macht.?event"],
}

def guess_category(name: str) -> str | None:
    n = (name or "").lower()
    for cat, pats in KEYWORDS.items():
        for p in pats:
            if re.search(p, n):
                return cat
    return None

# ------------------- Cog -------------------
class Analytics(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        setup_tables()

    # ---------- Admin: Meta setzen ----------
    @app_commands.command(name="event_meta_set",
                          description="Setzt Kategorie und Dauer (Minuten) für ein Event (ID aus /event_list).")
    @app_commands.describe(event_id="Event-ID", category="kvk | mge | other", duration_min="Dauerfenster in Minuten")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def event_meta_set(self, i: discord.Interaction, event_id: int, category: str, duration_min: int = 120):
        category = category.lower().strip()
        if category not in CATEGORIES:
            await i.response.send_message(f"Ungültige Kategorie. Erlaubt: {', '.join(CATEGORIES)}", ephemeral=True); return
        if duration_min < 10 or duration_min > 24*60:
            await i.response.send_message("Dauer bitte zwischen 10 und 1440 Minuten.", ephemeral=True); return

        con = db(EVT_DB)
        cur = con.cursor()
        # prüfen, ob Event existiert
        cur.execute("SELECT id FROM events WHERE id=?", (event_id,))
        if not cur.fetchone():
            con.close()
            await i.response.send_message("Event-ID nicht gefunden.", ephemeral=True); return

        cur.execute("""
        INSERT INTO event_meta(event_id, category, duration_min)
        VALUES(?,?,?)
        ON CONFLICT(event_id) DO UPDATE SET
            category=excluded.category,
            duration_min=excluded.duration_min
        """, (event_id, category, duration_min))
        con.commit(); con.close()
        await i.response.send_message(f"✅ Event `{event_id}` → Kategorie **{category}**, Dauer **{duration_min} min**", ephemeral=True)

    # ---------- Bericht: Buffs vs Events ----------
    @app_commands.command(name="report_buffs_vs_events",
                          description="Zeigt, wie viele Buffs während Events genutzt wurden vs. außerhalb.")
    async def report_buffs_vs_events(self, i: discord.Interaction, days: int = 30):
        await i.response.defer(ephemeral=True)
        since_ts = int((datetime.now(tz=timezone.utc) - timedelta(days=days)).timestamp())

        # 1) alle gestarteten Buff-Requests im Zeitraum holen
        con_b = db(AOE_DB); cb = con_b.cursor()
        cb.execute("""
            SELECT id, guild_id, start_ts, creator_id, confirmed_by
            FROM buff_requests
            WHERE guild_id=? AND started_sent=1 AND start_ts>=?
        """, (i.guild_id, since_ts))
        buffs = cb.fetchall()
        # dazu YES-Teilnehmer je Buff
        yes_map: dict[int, list[int]] = {}
        for rid, *_ in buffs:
            cb.execute("SELECT user_id FROM buff_participants WHERE request_id=? AND status='yes'", (rid,))
            yes_map[rid] = [u for (u,) in cb.fetchall()]
        con_b.close()

        # 2) Events + optional Meta laden
        con_e = db(EVT_DB); ce = con_e.cursor()
        ce.execute("""
            SELECT e.id, e.name, e.event_time, COALESCE(m.category, ''), COALESCE(m.duration_min, 0)
            FROM events e
            LEFT JOIN event_meta m ON m.event_id = e.id
            ORDER BY e.event_time ASC
        """)
        events = ce.fetchall()
        con_e.close()

        # Zeitfenster für Events vorbereiten
        evt_windows = []  # (id, category, start_ts, end_ts, name)
        for eid, name, etime, cat, dur in events:
            start = parse_dt(etime)
            if dur and dur > 0:
                end = start + timedelta(minutes=dur)
                category = cat or (guess_category(name) or "other")
            else:
                # wenn keine Dauer gesetzt → default 120min, Kategorie ggf. raten
                end = start + timedelta(minutes=120)
                category = cat or (guess_category(name) or "other")
            evt_windows.append((eid, category, int(start.timestamp()), int(end.timestamp()), name))

        # 3) Zuordnung: Buff-Zeitpunkt in eines der Event-Fenster?
        counts = {"kvk": 0, "mge": 0, "other": 0, "outside": 0}
        outside_users: dict[int, int] = {}  # user_id -> anzahl outside
        hits_by_event: dict[int, int] = {}

        for rid, guild_id, start_ts, creator_id, confirmed_by in buffs:
            matched = False
            for eid, cat, s, e, _name in evt_windows:
                if start_ts >= s and start_ts <= e:
                    counts[cat] = counts.get(cat, 0) + 1
                    hits_by_event[eid] = hits_by_event.get(eid, 0) + 1
                    matched = True
                    break
            if not matched:
                counts["outside"] += 1
                # Verursacher werten: alle Yes-Teilnehmer (oder zur Not Creator)
                users = yes_map.get(rid) or ([creator_id] if creator_id else [])
                for u in users:
                    outside_users[u] = outside_users.get(u, 0) + 1

        # 4) Ausgabe
        e = discord.Embed(title=f"📊 Buffs vs. Events – letzte {days} Tage", color=0x5865F2)
        e.add_field(name="KVK", value=str(counts.get("kvk", 0)))
        e.add_field(name="MGE", value=str(counts.get("mge", 0)))
        e.add_field(name="Other Events", value=str(counts.get("other", 0)))
        e.add_field(name="Außerhalb", value=str(counts.get("outside", 0)), inline=False)

        # Top „Outside“-User
        if outside_users:
            top = sorted(outside_users.items(), key=lambda x: x[1], reverse=True)[:10]
            lines = []
            for uid, c in top:
                m = i.guild.get_member(uid)
                name = m.display_name if m else f"<@{uid}>"
                lines.append(f"{name}: **{c}**")
            e.add_field(name="Top Outside-Nutzung", value="\n".join(lines), inline=False)

        await i.followup.send(embed=e, ephemeral=True)

    # ---------- Bericht: User-Detail ----------
    @app_commands.command(name="report_user_buffs",
                          description="Buff-Nutzung eines Spielers (in Events vs. außerhalb).")
    async def report_user_buffs(self, i: discord.Interaction, member: discord.Member, days: int = 30):
        await i.response.defer(ephemeral=True)
        since_ts = int((datetime.now(tz=timezone.utc) - timedelta(days=days)).timestamp())

        # Buff-Requests im Zeitraum
        con_b = db(AOE_DB); cb = con_b.cursor()
        cb.execute("""
            SELECT id, start_ts, creator_id
            FROM buff_requests
            WHERE guild_id=? AND started_sent=1 AND start_ts>=?
        """, (i.guild_id, since_ts))
        buffs = cb.fetchall()

        # Events + Meta
        con_e = db(EVT_DB); ce = con_e.cursor()
        ce.execute("""
            SELECT e.id, e.name, e.event_time, COALESCE(m.category, ''), COALESCE(m.duration_min, 0)
            FROM events e
            LEFT JOIN event_meta m ON m.event_id = e.id
        """)
        events = ce.fetchall()
        con_e.close()

        evt_windows = []
        for eid, name, etime, cat, dur in events:
            start = parse_dt(etime)
            end = start + timedelta(minutes=(dur if dur and dur>0 else 120))
            cat2 = cat or (guess_category(name) or "other")
            evt_windows.append((eid, cat2, int(start.timestamp()), int(end.timestamp())))

        inside = 0
        outside = 0

        # ist der User Teilnehmer (YES) oder Creator?
        for rid, ts, creator in buffs:
            cb.execute("SELECT 1 FROM buff_participants WHERE request_id=? AND user_id=? AND status='yes'", (rid, member.id))
            p = cb.fetchone()
            is_involved = p is not None or (creator == member.id)
            if not is_involved:
                continue
            in_event = any(s <= ts <= e for (_eid, _cat, s, e) in evt_windows)
            if in_event: inside += 1
            else: outside += 1
        con_b.close()

        await i.followup.send(
            f"👤 **{member.display_name}** – letzte {days} Tage\n"
            f"• Buffs **während Events**: **{inside}**\n"
            f"• Buffs **außerhalb**: **{outside}**",
            ephemeral=True
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(Analytics(bot))
