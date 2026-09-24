# cogs/matches.py
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
        score: str = "13-0",
        match_name: str = "",
        map_name: str = "",
    ):
        if winner.id == loser.id:
            await ctx.send("❌ Winner and loser can't be the same person.")
            return

        await db.add_match(winner.id, loser.id, score, match_name, map_name)

        embed = discord.Embed(
            title="✅ Match Recorded",
            color=0x00ff00,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Winner", value=winner.mention, inline=True)
        embed.add_field(name="Loser", value=loser.mention, inline=True)
        embed.add_field(name="Score", value=score, inline=True)
        if match_name:
            embed.add_field(name="Match", value=match_name, inline=True)
        if map_name:
            embed.add_field(name="Map", value=map_name, inline=True)
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
            color=0x00aaff,
        )
        for row in rows:
            # row = (id, p1, p2, winner_id, score, match_name, match_map, played_at)
            match_id, p1, p2, winner_id, score, m_name, m_map, played_at = row
            opponent_id = p2 if p1 == target.id else p1
            opponent = ctx.guild.get_member(opponent_id) if ctx.guild else None
            opponent_name = opponent.display_name if opponent else f"User {opponent_id}"

            result = "🟢 Win" if winner_id == target.id else "🔴 Loss"
            bits = [f"vs **{opponent_name}**", f"Score: `{score}`"]
            if m_name:
                bits.append(f"Match: `{m_name}`")
            if m_map:
                bits.append(f"Map: `{m_map}`")
            bits.append(str(played_at))
            embed.add_field(
                name=f"Match #{match_id} — {result}",
                value="\n".join(bits),
                inline=False,
            )
        await ctx.send(embed=embed)

    # ─── LIST TOURNAMENTS ───
    @commands.hybrid_command(name='listmatch', description='List all active tournaments by mode')
    async def listmatch(self, ctx):
        tournaments = await db.get_all_tournaments()
        active = [t for t in tournaments if t.get("status") != "draft"]

        if not active:
            await ctx.send("📭 No active tournaments yet. Check back later.")
            return

        embed = discord.Embed(
            title="🎮 Active Tournaments",
            description="Grouped by mode · use `/register` to join",
            color=0xFFB000,
        )

        for mode in ("1v1", "2v2", "5v5"):
            group = [t for t in active if t.get("mode") == mode]
            if not group:
                continue

            lines = []
            for t in group:
                slots = int(t.get("max_slots") or 32)
                reg = min(int(t.get("registered") or 0), slots)
                left = max(slots - reg, 0)
                status = str(t.get("status", "")).upper()
                lines.append(
                    f"**#{t['id']} {t['name']}** — `{status}`\n"
                    f"   {left}/{slots} slots left · starts {t.get('starts_at') or '—'}"
                )
            embed.add_field(
                name=f"▸ {mode}",
                value="\n".join(lines),
                inline=False,
            )

        embed.set_footer(text="Register with /register in Discord")
        await ctx.send(embed=embed)

    # ─── WIN COUNT ───
    @commands.hybrid_command(name='wincount', description='Top 10 players by total match wins')
    async def wincount(self, ctx):
        rows = await db.get_wins_leaderboard(10)
        if not rows:
            await ctx.send("📭 No matches recorded yet.")
            return

        lines = []
        for i, r in enumerate(rows, 1):
            member = ctx.guild.get_member(r["user_id"]) if ctx.guild else None
            name = member.display_name if member else f"User {r['user_id']}"
            lines.append(f"`#{i:>2}` **{name}** — {r['wins']} wins")

        embed = discord.Embed(
            title="🏆 Top 10 — Most Wins",
            description="\n".join(lines),
            color=0xFFB000,
        )
        await ctx.send(embed=embed)

    # ─── WINSTREAK ───
    @commands.hybrid_command(name='winstreak', description='Top 10 current winstreaks')
    async def winstreak(self, ctx):
        rows = await db.get_winstreaks(10)
        if not rows:
            await ctx.send("📭 No matches recorded yet.")
            return

        lines = []
        for i, r in enumerate(rows, 1):
            member = ctx.guild.get_member(r["user_id"]) if ctx.guild else None
            name = member.display_name if member else f"User {r['user_id']}"
            lines.append(f"`#{i:>2}` **{name}** — 🔥 {r['streak']} in a row")

        embed = discord.Embed(
            title="🔥 Current Winstreaks — Top 10",
            description="\n".join(lines),
            color=0xFFB000,
        )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Matches(bot))
