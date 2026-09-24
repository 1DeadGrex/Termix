# app.py — bot-hosting.net entry point (Discord bot + FastAPI in one process)
import asyncio
import os
import sys
import itertools
import uvicorn
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

load_dotenv()

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


intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True          # ← needed for on_voice_state_update

bot = commands.Bot(command_prefix="!", intents=intents)
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
    "cogs.welcome",
    "cogs.voice",                     # ← new
]


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
            activity = discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{len(players)} players registered",
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


@bot.event
async def on_command_error(ctx, error):
    if hasattr(ctx.command, "on_error"):
        return
    if isinstance(error, commands.CommandNotFound):
        return

    if isinstance(error, commands.MissingPermissions):
        perms = ", ".join(f"`{p}`" for p in (error.missing_permissions or []))
        await ctx.send(f"🚫 Only staff with {perms} can use `{ctx.command.qualified_name}`.")
        return
    if isinstance(error, commands.MissingRole):
        await ctx.send(f"🚫 Only {error.missing_role} can use `{ctx.command.qualified_name}`.")
        return
    if isinstance(error, commands.MissingAnyRole):
        roles = ", ".join(str(r) for r in (error.missing_roles or []))
        await ctx.send(f"🚫 Only these roles can use `{ctx.command.qualified_name}`: {roles}")
        return
    if isinstance(error, commands.CheckFailure):
        await ctx.send(f"🚫 {error} — you don't have permission to use `{ctx.command.qualified_name}`.")
        return
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❓ Missing argument: `{error.param.name}`. See `/help {ctx.command.qualified_name}`.")
        return
    if isinstance(error, commands.BadArgument):
        await ctx.send(f"❓ {error} — check your input format.")
        return
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏳ Slow down — try again in `{error.retry_after:.1f}s`.")
        return

    print(f"[command error] {ctx.command}: {type(error).__name__}: {error}")
    try:
        import traceback
        traceback.print_exception(type(error), error, error.__traceback__)
    except Exception:
        pass
    await ctx.send(
        f"❌ Something went wrong running `{ctx.command.qualified_name}` — "
        f"please tell a staff member. (`{type(error).__name__}`)"
    )


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
    port = int(os.getenv("SERVER_PORT") or os.getenv("PORT") or "8000")
    print(f"🌐 Starting API on port {port}")
    config = uvicorn.Config(
        api.app, host="0.0.0.0", port=port, log_level="info", access_log=False,
    )
    server = uvicorn.Server(config)
    await server.serve()


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
