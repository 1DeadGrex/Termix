# cogs/levels.py
import discord
from discord.ext import commands
import time
from utils import database as db

# ─── XP settings ───
XP_PER_MESSAGE = 10
COOLDOWN_SECONDS = 60

# In-memory cooldown: {user_id: last_message_ts}
_cooldown: dict[int, float] = {}


class Levels(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore bots, DMs, and command-prefixed messages
        if message.author.bot or not message.guild:
            return
        content = message.content or ""
        if content.startswith(("!", "/", ".", "?")):
            return

        uid = message.author.id
        now = time.time()
        if now - _cooldown.get(uid, 0) < COOLDOWN_SECONDS:
            return
        _cooldown[uid] = now

        try:
            xp, level = await db.add_xp(uid, message.guild.id, XP_PER_MESSAGE)
        except Exception as e:
            print(f"[levels] add_xp failed for {uid}: {e}")
            return

        # Level-up announcement (old level approximated from xp before this message)
        try:
            old_level = int(((xp - XP_PER_MESSAGE) / 100) ** 0.5)
            if level > old_level and level > 0:
                await message.channel.send(
                    f"🎉 {message.author.mention} reached **level {level}**!"
                )
        except Exception as e:
            print(f"[levels] announce failed: {e}")

    @commands.hybrid_command(name="leaderboard", description="Top 10 XP earners")
    async def leaderboard(self, ctx):
        try:
            rows = await db.get_global_leaderboard(10)
        except Exception as e:
            await ctx.send(f"❌ Leaderboard unavailable right now: `{e}`")
            return

        if not rows:
            await ctx.send(
                "📭 **No XP on record yet.** Chat in the server to start earning XP — "
                "10 XP per message, 60s cooldown between earning messages."
            )
            return

        lines = []
        for r in rows:
            uid = r["user_id"]
            member = ctx.guild.get_member(uid) if ctx.guild else None
            name = member.display_name if member else f"User {uid}"
            lines.append(
                f"`#{r['rank']:>2}` **{name}** — LVL {r['level']} · {r['xp']} XP"
            )

        embed = discord.Embed(
            title="🏆 XP Leaderboard — Top 10",
            description="\n".join(lines),
            color=0xFFB000,
        )
        embed.set_footer(text="10 XP per message · 60s cooldown")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="myxp", description="Show your XP and level")
    async def myxp(self, ctx):
        try:
            rows = await db.get_global_leaderboard(500)
        except Exception as e:
            await ctx.send(f"❌ XP lookup unavailable: `{e}`")
            return

        me = next((r for r in rows if r["user_id"] == ctx.author.id), None)
        if not me:
            await ctx.send(
                f"{ctx.author.mention} — no XP on record yet. Send a few messages to get started."
            )
            return

        next_xp = ((me["level"] + 1) ** 2) * 100
        to_next = max(0, next_xp - me["xp"])
        embed = discord.Embed(title=f"📊 {ctx.author.display_name}", color=0xFFB000)
        embed.add_field(name="Level", value=str(me["level"]), inline=True)
        embed.add_field(name="Total XP", value=f"{me['xp']}", inline=True)
        embed.add_field(name="Global Rank", value=f"#{me['rank']}", inline=True)
        embed.add_field(name="To next level", value=f"{to_next} XP (at {next_xp} XP)", inline=False)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Levels(bot))
