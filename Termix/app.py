# app.py — bot-hosting.net entry point
# Runs Discord bot + FastAPI in one process.

import asyncio
import os
import sys
import itertools
import uvicorn
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

load_dotenv()

# ── Imports with clear errors ──
try:
    import api
except Exception as e:
    print(f"❌ Failed to import api.py: {e}")
    sys.exit(1)

try:
    from utils import database as db
except Exception as e:
    print(f"❌ Failed to import utils.database: {e}")
    sys.exit(1)


# ─────────────────────────────────────────────
# Bot setup
# ─────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Give the API a reference to the bot (enables /api/discord/{id})
api.set_bot(bot)


COGS_TO_LOAD = [
    "cogs.general",
    "cogs.registration",
    "cogs.giveaways",
    "cogs.announcements",
    "cogs.moderation",
    "cogs.matches",
    "cogs.levels",
    "cogs.counting",
    "cogs.server_info",
    "cogs.tickets",
]


# ─────────────────────────────────────────────
# Rich presence rotation
# ─────────────────────────────────────────────
STATUSES = [
    ("playing", "Counter-Strike 2"),
    ("watching", "1v1 Tournament"),
    ("playing", "on Termix"),
    ("listening", "to your commands"),
]
_status_cycle = itertools.cycle(STATUSES)


@tasks.loop(seconds=45)
async def rotate_presence():
    if rotate_presence.current_loop % 4 == 3:
        try:
            players = await db.get_all_players()
            count = len(players)
            activity = discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{count} players registered",
            )
        except Exception:
            activity = discord.Game(name="Counter-Strike 2")
    else:
        kind, text = next(_status_cycle)
        if kind == "playing":
            activity = discord.Game(name=text)
        elif kind == "watching":
            activity = discord.Activity(type=discord.ActivityType.watching, name=text)
        elif kind == "listening":
            activity = discord.Activity(type=discord.ActivityType.listening, name=text)
        else:
            activity = discord.Game(name=text)

    try:
        await bot.change_presence(activity=activity, status=discord.Status.online)
    except Exception as e:
        print(f"presence error: {e}")


@rotate_presence.before_loop
async def before_rotate():
    await bot.wait_until_ready()


# ─────────────────────────────────────────────
# on_ready
# ─────────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"\n✅ {bot.user} is online!")
    for g in bot.guilds:
        print(f"   Connected to: {g.name} (ID: {g.id})")
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} slash command(s)")
    except Exception as e:
        print(f"❌ Slash sync failed: {e}")
    print(f"✅ Loaded commands: {sorted(c.name for c in bot.commands)}")

    if not rotate_presence.is_running():
        rotate_presence.start()
        print("✅ Presence rotation started")

    print("─" * 50)


# ─────────────────────────────────────────────
# Run bot
# ─────────────────────────────────────────────
async def run_bot():
    async with bot:
        for cog in COGS_TO_LOAD:
            try:
                await bot.load_extension(cog)
                print(f"✅ Loaded {cog}")
            except Exception as e:
                print(f"❌ Failed {cog}: {e}")
        await bot.start(os.getenv("DISCORD_TOKEN"))


# ─────────────────────────────────────────────
# Run API
# ─────────────────────────────────────────────
async def run_api():
    port = int(os.getenv("SERVER_PORT") or os.getenv("PORT") or "8000")
    print(f"🌐 Starting API on port {port}")
    config = uvicorn.Config(
        api.app,
        host="0.0.0.0",
        port=port,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)
    await server.serve()


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
async def main():
    await db.init_db()
    print("✅ DB initialized")
    port = os.getenv("SERVER_PORT") or os.getenv("PORT") or "8000"
    print(f"🚀 Starting bot + API on port {port}")
    print("─" * 50)
    await asyncio.gather(run_bot(), run_api())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Shutting down...")
