import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord.ui import View, Button
import asyncio
import sqlite3
import datetime
import os

# Sprache-Übersetzung: Dummy (hier DeepL API oder ähnliches einbauen)
def translate_message(text, target_lang):
    translations = {
        "en": f"[EN] {text}",
        "de": f"[DE] {text}",
        "es": f"[ES] {text}",
        "fr": f"[FR] {text}"
    }
    return translations.get(target_lang, text)

class ConfirmView(View):
    def __init__(self, message_id):
        super().__init__(timeout=None)
        self.message_id = message_id

    @discord.ui.button(label="✅ Gesehen", style
