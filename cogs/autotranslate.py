import os, aiohttp, discord
from typing import Dict
from discord.ext import commands

LANGS = {"de":"German","en":"English","es":"Spanish","fr":"French"}

def _k(guild_id: int, channel_id: int) -> str:
    return f"{guild_id}:{channel_id}"

class AutoTranslate(commands.Cog):
    """Kanalsprache + Channel-Bridge via LibreTranslate (de/en/es/fr)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.channel_lang: Dict[str,str] = {}        # key -> "de"/"en"/"es"/"fr"
        self.bridges: Dict[str, Dict[str,int]] = {}  # key -> {"en":chan_id, ...}
        self.libre_url = os.getenv("LIBRE_URL", "https://libretranslate.com")

    async def translate(self, text: str, src: str, tgt: str) -> str:
        if src == tgt:
            return text
        url = f"{self.libre_url}/translate"
        payload = {"q": text, "source": src, "target": tgt, "format": "text"}
        async with aiohttp.ClientSession() as s:
            async with s.post(url, json=payload, timeout=20) as r:
                r.raise_for_status()
                data = await r.json()
                if isinstance(data, dict) and "translatedText" in data:
                    return data["translatedText"]
                if isinstance(data, list) and data and "translatedText" in data[0]:
                    return data[0]["translatedText"]
                return text

    @discord.app_commands.command(name="autotranslate_set",
                                  description="Setzt die Kanalsprache (de/en/es/fr).")
    @discord.app_commands.describe(lang="de | en | es | fr")
    async def autotranslate_set(self, itx: discord.Interaction, lang: str):
        lang = lang.lower()
        if lang not in LANGS:
            await itx.response.send_message("Nur de/en/es/fr erlaubt.", ephemeral=True)
            return
        key = _k(itx.guild_id, itx.channel_id)
        self.channel_lang[key] = lang
        await itx.response.send_message(
            f"✅ Sprache für {itx.channel.mention} auf **{lang}** gesetzt.",
            ephemeral=True
        )

    @discord.app_commands.command(name="autotranslate_show",
                                  description="Zeigt Sprache & Bridge dieses Kanals.")
    async def autotranslate_show(self, itx: discord.Interaction):
        key = _k(itx.guild_id, itx.channel_id)
        lang = self.channel_lang.get(key, "— (nicht gesetzt)")
        b = self.bridges.get(key, {})
        lines = [f"**Kanal**: {itx.channel.mention}",
                 f"**Sprache**: {lang}",
                 "**Bridge-Ziele**:"]
        if not b:
            lines.append("—")
        else:
            for code, cid in b.items():
                ch = itx.guild.get_channel(cid)
                lines.append(f"{lang} → {code} : {ch.mention if ch else cid}")
        await itx.response.send_message("\n".join(lines), ephemeral=True)

    @discord.app_commands.command(name="bridge_set",
                                  description="Setzt Zielkanäle für EN/ES/FR.")
    @discord.app_commands.describe(en="EN-Kanal", es="ES-Kanal", fr="FR-Kanal")
    async def bridge_set(self, itx: discord.Interaction,
                         en: discord.TextChannel=None,
                         es: discord.TextChannel=None,
                         fr: discord.TextChannel=None):
        key = _k(itx.guild_id, itx.channel_id)
        cfg = self.bridges.get(key, {})
        if en: cfg["en"] = en.id
        if es: cfg["es"] = es.id
        if fr: cfg["fr"] = fr.id
        self.bridges[key] = cfg
        await itx.response.send_message("✅ Bridge gespeichert.", ephemeral=True)

    @discord.app_commands.command(name="bridge_show", description="Zeigt Bridge-Ziele.")
    async def bridge_show(self, itx: discord.Interaction):
        key = _k(itx.guild_id, itx.channel_id)
        cfg = self.bridges.get(key, {})
        if not cfg:
            await itx.response.send_message("Keine Bridge konfiguriert.", ephemeral=True)
            return
        lines = []
        for code, cid in cfg.items():
            ch = itx.guild.get_channel(cid)
            lines.append(f"{code} → {ch.mention if ch else cid}")
        await itx.response.send_message("\n".join(lines), ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, msg: discord.Message):
        if msg.author.bot or not msg.guild or not msg.content:
            return
        key = _k(msg.guild.id, msg.channel.id)
        src = self.channel_lang.get(key)
        if not src:
            return  # keine Sprache gesetzt → nichts tun
        targets = self.bridges.get(key, {})
        if not targets:
            return
        for tgt, chan_id in targets.items():
            try:
                out = await self.translate(msg.content, src, tgt)
                ch = msg.guild.get_channel(chan_id)
                if ch:
                    await ch.send(f"**{msg.author.display_name}** ({src}→{tgt}): {out}")
            except Exception as e:
                print("[AUTOTRANS] error:", repr(e))

async def setup(bot: commands.Bot):
    await bot.add_cog(AutoTranslate(bot))
