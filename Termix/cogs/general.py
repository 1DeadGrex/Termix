# cogs/general.py
import discord
from discord.ext import commands


HELP_SECTIONS = [
    ("🎮 GENERAL", [
        ("/ping", "Check bot latency"),
        ("/hello", "Say hello"),
        ("/help", "Show this command list"),
        ("/serverinfo", "Show server stats"),
    ]),
    ("📝 REGISTRATION", [
        ("/register", "Start Steam verification (link arrives in DMs)"),
        ("/whoami [member]", "Show Discord↔Steam link + XP (self-view is private)"),
        ("/unregister @user", "[Admin] Remove a registration"),
        ("/force_register [steam_id]", "[Admin] Skip Steam auth"),
    ]),
    ("🏆 TOURNAMENTS", [
        ("/listmatch", "List active tournaments by mode"),
        ("/report_match", "[Admin] Record a match result"),
        ("/matchhistory [member]", "Last 10 matches for a player"),
    ]),
    ("📊 STATS", [
        ("/wincount", "Top 10 by total wins"),
        ("/winstreak", "Top 10 by current winstreak"),
        ("/leaderboard", "Top 10 by XP"),
        ("/myxp", "Your XP, level, and rank"),
    ]),
    ("🛡️ MODERATION", [
        ("/banlist", "[Staff] View bans"),
        ("/ban_player @user", "[Staff] Ban Discord + linked Steam"),
        ("/ban_steam <id>", "[Staff] Ban a Steam ID directly"),
        ("/unban <discord_id>", "[Staff] Unban a user"),
        ("/unban_steam <id>", "[Staff] Remove a Steam ban"),
        ("/lock /unlock", "[Staff] Toggle channel speech"),
        ("/nuke", "[Staff] Clone + reset this channel"),
        ("/purge N", "[Staff] Delete last N messages"),
    ]),
    ("🎫 TICKETS & WELCOME", [
        ("/setup_tickets", "[Admin] Post the ticket panel"),
        ("/ticket", "Open a support ticket"),
        ("/setup_welcome", "[Admin] Configure welcome message"),
        ("/welcome_preview / /welcome_clear", "[Admin] Manage welcome"),
    ]),
    ("🎧 VOICE", [
        ("/party invite @user", "Give someone access to your temp VC"),
        ("/party kick @user", "Revoke access + disconnect"),
        ("/party end", "Delete your temp VC"),
        ("/party info", "Show your temp VC"),
    ]),
    ("🎁 MISC", [
        ("/giveaway <duration> <prize>", "[Admin] Start a giveaway"),
        ("/announce <msg>", "[Admin] Post an announcement"),
        ("/set_counting_channel", "[Admin] Configure counting"),
        ("/reset_counting", "[Admin] Reset the count"),
    ]),
]


class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name='ping', description='Check bot latency')
    async def ping(self, ctx):
        latency = round(self.bot.latency * 1000)
        await ctx.send(f'🏓 Pong! Latency: `{latency}ms`')

    @commands.hybrid_command(name='hello', description='Say hello')
    async def hello(self, ctx):
        await ctx.send(f'👋 Hello {ctx.author.mention}!')

    @commands.hybrid_command(name='help', description='List all commands by category')
    async def help(self, ctx):
        embed = discord.Embed(
            title="📖 TERMIX — Command Reference",
            description="All commands work as both `/slash` and `!prefix`.",
            color=0xFFB000,
        )
        for section, cmds in HELP_SECTIONS:
            value = "\n".join(f"`{name}` — {desc}" for name, desc in cmds)
            embed.add_field(name=section, value=value[:1024], inline=False)
        embed.set_footer(text="Staff commands require the STAFF role or admin perms.")
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(General(bot))
