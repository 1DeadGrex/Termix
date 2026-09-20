import discord
from discord.ext import commands
import os
import asyncio
from dotenv import load_dotenv

load_dotenv()

# ---------- Intents ----------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# ---------- Bot Instance ----------
bot = commands.Bot(command_prefix='!', intents=intents)

# ---------- Cogs to Load ----------
COGS_TO_LOAD = [
    'cogs.registration',
    'cogs.giveaways',
    'cogs.announcements',
    'cogs.moderation',
    'cogs.matches',
    'cogs.levels',
    'cogs.counting',
    'cogs.server_info',
]

# ---------- Events ----------
@bot.event
async def on_ready():
    print(f'{bot.user} is online!')
    print(f'Connected to {len(bot.guilds)} server(s):')
    for g in bot.guilds:
        print(f'  - {g.name} (ID: {g.id})')
    print(f'Prefix: {bot.command_prefix}')
    print(f'Loaded commands: {[c.name for c in bot.commands]}')
    try:
        synced = await bot.tree.sync()
        print(f'Synced {len(synced)} slash command(s)')
    except Exception as e:
        print(f'Failed to sync slash commands: {e}')

# ---------- Main ----------
async def main():
    async with bot:
        for cog in COGS_TO_LOAD:
            try:
                await bot.load_extension(cog)
                print(f'✅ Loaded {cog}')
            except Exception as e:
                print(f'❌ Failed to load {cog}: {e}')
        await bot.start(os.getenv('DISCORD_TOKEN'))

if __name__ == "__main__":
    asyncio.run(main())