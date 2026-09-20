import discord
from discord.ext import commands
from utils import database as db


class Matches(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ─── REPORT A MATCH ───
    @commands.hybrid_command(name='report_match', description='[Staff] Record a match result')
    @commands.has_permissions(administrator=True)
    async def report_match(
        self,
        ctx,
        winner: discord.Member,
        loser: discord.Member,
        score: str = "13-0"
    ):
        if winner.id == loser.id:
            await ctx.send("❌ Winner and loser can't be the same person.")
            return

        await db.add_match(winner.id, loser.id, score)

        embed = discord.Embed(
            title="✅ Match Recorded",
            color=0x00ff00,
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="Winner", value=winner.mention, inline=True)
        embed.add_field(name="Loser", value=loser.mention, inline=True)
        embed.add_field(name="Score", value=score, inline=False)
        await ctx.send(embed=embed)

    # ─── MATCH HISTORY ───
    @commands.hybrid_command(name='matchhistory', description='View match history')
    async def matchhistory(self, ctx, member: discord.Member = None):
        target = member or ctx.author
        rows = await db.get_match_history(target.id, limit=10)

        if not rows:
            await ctx.send(f"📭 No match history for {target.mention}.")
            return

        embed = discord.Embed(
            title=f"📊 Match History — {target.display_name}",
            color=0x00aaff
        )
        for row in rows:
            match_id, p1, p2, winner_id, score, played_at = row
            opponent_id = p2 if p1 == target.id else p1
            opponent = ctx.guild.get_member(opponent_id)
            opponent_name = opponent.display_name if opponent else f"User {opponent_id}"

            result = "🟢 Win" if winner_id == target.id else "🔴 Loss"
            embed.add_field(
                name=f"Match #{match_id} — {result}",
                value=f"vs **{opponent_name}**\nScore: `{score}`\n{played_at}",
                inline=False
            )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Matches(bot))