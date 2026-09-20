import discord
from discord.ext import commands
import aiosqlite
import time

xp_cooldowns = {}

class Levels(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
        if message.content.startswith(self.bot.command_prefix):
            return

        user_id = message.author.id
        guild_id = message.guild.id
        now = time.time()

        if user_id in xp_cooldowns and now - xp_cooldowns[user_id] < 60:
            return
        xp_cooldowns[user_id] = now

        async with aiosqlite.connect('tournament.db') as db:
            await db.execute(
                'INSERT INTO xp (user_id, guild_id, xp) VALUES (?, ?, 10) '
                'ON CONFLICT(user_id, guild_id) DO UPDATE SET xp = xp + 10',
                (user_id, guild_id)
            )
            await db.commit()

            async with db.execute(
                'SELECT xp FROM xp WHERE user_id = ? AND guild_id = ?',
                (user_id, guild_id)
            ) as cursor:
                row = await cursor.fetchone()
                xp = row[0] if row else 0

            new_level = int((xp / 100) ** 0.5)
            await db.execute(
                'UPDATE xp SET level = ? WHERE user_id = ? AND guild_id = ?',
                (new_level, user_id, guild_id)
            )
            await db.commit()

    @commands.hybrid_command(name='leaderboard', description='View XP leaderboard')
    async def leaderboard(self, ctx):
        async with aiosqlite.connect('tournament.db') as db:
            async with db.execute(
                'SELECT user_id, xp, level FROM xp WHERE guild_id = ? ORDER BY xp DESC LIMIT 10',
                (ctx.guild.id,)
            ) as cursor:
                rows = await cursor.fetchall()

        embed = discord.Embed(title="🏆 XP Leaderboard", color=0xffd700)
        for i, row in enumerate(rows, 1):
            member = ctx.guild.get_member(row[0])
            name = member.display_name if member else f"User {row[0]}"
            embed.add_field(name=f"#{i} {name}", value=f"XP: {row[1]} | Level: {row[2]}", inline=False)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Levels(bot))  