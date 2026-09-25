# cogs/levels.py
import discord
from discord.ext import commands, tasks
import asyncio
import time
from utils import database as db
import config

XP_PER_MESSAGE = 10
COOLDOWN_SECONDS = 60
_cooldown: dict[int, float] = {}


def _progress_bar(current: int, total: int, width: int = 12) -> str:
    if total <= 0:
        return "▰" * width
    filled = max(0, min(width, round(current / total * width)))
    return "▰" * filled + "▱" * (width - filled)


class Levels(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        if not self.leaderboard_update.is_running():
            self.leaderboard_update.start()

    async def cog_unload(self):
        if self.leaderboard_update.is_running():
            self.leaderboard_update.cancel()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
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
            xp, level, leveled_up, coins_earned = await db.add_xp(
                uid, message.guild.id, XP_PER_MESSAGE,
                coins_per_level=getattr(config, "COINS_PER_LEVEL", 50),
            )
        except Exception as e:
            print(f"[levels] add_xp failed for {uid}: {e}")
            return

        if leveled_up and level > 0:
            try:
                await message.channel.send(
                    f"🎉 {message.author.mention} reached **level {level}** — "
                    f"earned **{coins_earned} E-coins**! 💰"
                )
            except Exception as e:
                print(f"[levels] announce failed: {e}")

    @commands.hybrid_command(name="leaderboard", description="Top 10 XP earners")
    async def leaderboard(self, ctx):
        try:
            rows = await db.get_global_leaderboard(10)
        except Exception as e:
            await ctx.send(f"❌ Leaderboard unavailable: `{e}`")
            return
        if not rows:
            await ctx.send("📭 No XP yet — chat in the server to earn XP and E-coins!")
            return

        lines = []
        for r in rows:
            member = ctx.guild.get_member(r["user_id"]) if ctx.guild else None
            name = member.display_name if member else f"User {r['user_id']}"
            lines.append(
                f"`#{r['rank']:>2}` **{name}** — LVL {r['level']} · "
                f"{r['xp']} XP · {r.get('coins', 0)} 💰"
            )
        embed = discord.Embed(title="🏆 XP Leaderboard — Top 10",
                              description="\n".join(lines), color=0xFFB000)
        embed.set_footer(text="10 XP / message · 60s cooldown · 50 E-coins per level-up")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="myxp", description="Show your XP, level, E-coins and progress")
    async def myxp(self, ctx):
        try:
            me = await db.get_user_xp(ctx.author.id)
        except Exception as e:
            await ctx.send(f"❌ XP lookup unavailable: `{e}`")
            return

        # Compute rank
        rank = None
        try:
            lb = await db.get_global_leaderboard(500)
            for r in lb:
                if r["user_id"] == ctx.author.id:
                    rank = r["rank"]
                    break
        except Exception:
            pass

        xp = me["xp"]
        level = me["level"]
        coins = me["coins"]

        cur_level_xp = (level ** 2) * 100
        next_level_xp = ((level + 1) ** 2) * 100
        into_level = max(0, xp - cur_level_xp)
        needed = max(1, next_level_xp - cur_level_xp)
        to_next = max(0, next_level_xp - xp)

        bar = _progress_bar(into_level, needed)

        embed = discord.Embed(title=f"📊 {ctx.author.display_name}", color=0xFFB000)
        embed.set_thumbnail(url=ctx.author.display_avatar.url)
        embed.add_field(name="Level", value=str(level), inline=True)
        embed.add_field(name="Total XP", value=f"{xp}", inline=True)
        embed.add_field(name="E-coins 💰", value=str(coins), inline=True)
        if rank is not None:
            embed.add_field(name="Global Rank", value=f"#{rank}", inline=True)
        embed.add_field(
            name=f"Progress to Level {level + 1}",
            value=f"`{bar}`  {into_level}/{needed}\n"
                  f"**{to_next} XP** more to level up "
                  f"(at {next_level_xp} XP)",
            inline=False,
        )
        embed.set_footer(text="10 XP per message · 50 E-coins per level-up")
        await ctx.send(embed=embed)

    # ─── AUTO LEADERBOARD (edits the same message) ───
    @tasks.loop(hours=6)
    async def leaderboard_update(self):
        await self._post_leaderboard()

    @leaderboard_update.before_loop
    async def _before_leaderboard(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(30)
        await self._post_leaderboard()

    async def _post_leaderboard(self):
        try:
            ch_id = getattr(config, "LEADERBOARD_CHANNEL_ID", 0) or 0
            if not ch_id:
                return
            channel = self.bot.get_channel(ch_id)
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(ch_id)
                except Exception as e:
                    print(f"[levels] leaderboard fetch failed: {e}")
                    return

            rows = await db.get_global_leaderboard(10)
            if not rows:
                return

            guild = channel.guild
            lines = []
            for r in rows:
                member = guild.get_member(r["user_id"]) if guild else None
                name = member.display_name if member else f"User {r['user_id']}"
                lines.append(
                    f"`#{r['rank']:>2}` **{name}** — LVL {r['level']} · "
                    f"{r['xp']} XP · {r.get('coins', 0)} 💰"
                )

            embed = discord.Embed(
                title="🏆 ERVSE LEADERBOARD",
                description="Top 10 by XP · auto-refreshed every 6 hours\n\n" + "\n".join(lines),
                color=0xFFB000,
            )
            embed.set_footer(text="Use /leaderboard anytime · /myxp to check yourself")

            edited = False
            stored_id = await db.get_leaderboard_message_id(guild.id)
            if stored_id:
                try:
                    msg = await channel.fetch_message(int(stored_id))
                    await msg.edit(embed=embed)
                    edited = True
                except discord.NotFound:
                    await db.clear_leaderboard_message_id(guild.id)
                except discord.Forbidden:
                    print("[levels] cannot edit — no permission")
                except Exception as e:
                    print(f"[levels] edit failed: {e}")

            if not edited:
                sent = await channel.send(embed=embed)
                await db.set_leaderboard_message_id(guild.id, sent.id)
                print(f"[levels] posted new leaderboard message in {channel.name}")
            else:
                print(f"[levels] edited leaderboard message in {channel.name}")

        except Exception as e:
            print(f"[levels] task error: {e}")


async def setup(bot):
    await bot.add_cog(Levels(bot))
