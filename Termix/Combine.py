# combine.py — runs the Discord bot + FastAPI in one process
import asyncio
import os
import sys
import uvicorn
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

# ─── Load FastAPI app ───
try:
    from api import app
except Exception as e:
    print(f"❌ Failed to import api.py: {e}")
    sys.exit(1)

# ─── Load DB helpers ───
try:
    from utils import database as db
except Exception as e:
    print(f"❌ Failed to import utils.database: {e}")
    sys.exit(1)


# ─── Discord bot setup ───
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

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
    print("─" * 50)


async def run_bot():
    async with bot:
        for cog in COGS_TO_LOAD:
            try:
                await bot.load_extension(cog)
                print(f"✅ Loaded {cog}")
            except Exception as e:
                print(f"❌ Failed {cog}: {e}")
        await bot.start(os.getenv("DISCORD_TOKEN"))


async def run_api():
    port = int(os.getenv("PORT", "8000"))
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    await db.init_db()
    print("✅ DB initialized")
    print(f"🚀 Starting bot + API on port {os.getenv('PORT', '8000')}")
    print("─" * 50)
    await asyncio.gather(run_bot(), run_api())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Shutting down...")