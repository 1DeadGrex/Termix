# cogs/matches.py
import discord
from discord.ext import commands
from discord import app_commands
from utils import database as db


class ConfirmMatchView(discord.ui.View):
    """Sent via DM to both players. Buttons confirm/reject."""
    def __init__(self, pending_id: int, user_id: int):
        super().__init__(timeout=3600)
        self.pending_id = pending_id
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This confirmation isn't for you.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="CONFIRM", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        ok, status = await db.confirm_pending_match(self.pending_id, self.user_id)
        if not ok:
            await interaction.response.send_message("❌ Confirmation failed.", ephemeral=True)
            return

        if status == "both_confirmed":
            # Match fully recorded
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(
                content="✅ **Confirmed — match recorded.**", view=self
            )
            pm = None  # can't re-fetch (deleted) — the other player's view will show one_confirmed
        elif status == "already":
            await interaction.response.send_message("You already confirmed.", ephemeral=True)
        else:
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(
                content="✅ **You confirmed.** Waiting on the other player…", view=self
            )

    @discord.ui.button(label="REJECT", style=discord.ButtonStyle.danger, emoji="❌")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await db.reject_pending_match(self.pending_id)
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content="❌ **Rejected — this match report is cancelled.**", view=self
        )


class Matches(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ─── REPORT A MATCH (legacy direct) ───
    @commands.hybrid_command(name='report_match', description='[Staff] Record a match immediately')
    @commands.has_permissions(administrator=True)
    async def report_match(
        self, ctx,
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
        embed = discord.Embed(title="✅ Match Recorded", color=0x00ff00,
                              timestamp=discord.utils.utcnow())
        embed.add_field(name="Winner", value=winner.mention, inline=True)
        embed.add_field(name="Loser", value=loser.mention, inline=True)
        embed.add_field(name="Score", value=score, inline=True)
        if match_name: embed.add_field(name="Match", value=match_name, inline=True)
        if map_name: embed.add_field(name="Map", value=map_name, inline=True)
        await ctx.send(embed=embed)

    # ─── CONFIRM MATCH (both players must agree) ───
    @commands.hybrid_command(name='confirm_match', description='Report a match — both players must confirm via DM')
    @app_commands.describe(
        opponent="The other player",
        won="True if YOU won, False if you lost",
        score="Score, e.g. 13-7",
        match_name="Optional match/tournament name",
        map_name="Optional map",
    )
    async def confirm_match(
        self, ctx,
        opponent: discord.Member,
        won: bool,
        score: str,
        match_name: str = "",
        map_name: str = "",
    ):
        if opponent.id == ctx.author.id:
            await ctx.send("❌ You can't report a match against yourself.", ephemeral=True)
            return
        if opponent.bot:
            await ctx.send("❌ Can't report a match against a bot.", ephemeral=True)
            return

        winner_id = ctx.author.id if won else opponent.id
        loser_id = opponent.id if won else ctx.author.id

        pid = await db.add_pending_match(winner_id, loser_id, score,
                                         match_name, map_name, ctx.author.id)

        # DM both
        for uid in (winner_id, loser_id):
            try:
                user = self.bot.get_user(uid) or await self.bot.fetch_user(uid)
                embed = discord.Embed(
                    title="🎮 Match Confirmation Required",
                    description=(
                        f"**Reported by:** <@{ctx.author.id}>\n"
                        f"**Winner:** <@{winner_id}>\n"
                        f"**Loser:** <@{loser_id}>\n"
                        f"**Score:** `{score}`"
                        + (f"\n**Match:** {match_name}" if match_name else "")
                        + (f"\n**Map:** {map_name}" if map_name else "")
                        + "\n\nBoth players must **CONFIRM** for this to be recorded."
                    ),
                    color=0xFFB000,
                )
                await user.send(embed=embed, view=ConfirmMatchView(pid, uid))
            except discord.Forbidden:
                await ctx.send(f"⚠️ Couldn't DM <@{uid}> — they need to open DMs.", ephemeral=True)
            except Exception as e:
                print(f"[confirm_match] DM failed for {uid}: {e}")

        await ctx.send(
            f"✅ Match **pending confirmation** — both players have been DM'd with buttons.",
            ephemeral=True,
        )

    # ─── MATCH HISTORY ───
    @commands.hybrid_command(name='matchhistory', description='View match history')
    async def matchhistory(self, ctx, member: discord.Member = None):
        target = member or ctx.author
        rows = await db.get_match_history(target.id, limit=10)
        if not rows:
            await ctx.send(f"📭 No match history for {target.mention}.")
            return

        embed = discord.Embed(title=f"📊 Match History — {target.display_name}", color=0x00aaff)
        for row in rows:
            match_id, p1, p2, winner_id, score, m_name, m_map, played_at = row
            opponent_id = p2 if p1 == target.id else p1
            opponent = ctx.guild.get_member(opponent_id) if ctx.guild else None
            opponent_name = opponent.display_name if opponent else f"User {opponent_id}"

            result = "🟢 Win" if winner_id == target.id else "🔴 Loss"
            bits = [f"vs **{opponent_name}**", f"Score: `{score}`"]
            if m_name: bits.append(f"Match: `{m_name}`")
            if m_map: bits.append(f"Map: `{m_map}`")
            bits.append(str(played_at))
            embed.add_field(name=f"Match #{match_id} — {result}",
                            value="\n".join(bits), inline=False)
        await ctx.send(embed=embed)

    # ─── LIST MATCHES (FIXED — shows OCCUPIED/TOTAL) ───
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
                occupied = min(int(t.get("registered") or 0), slots)
                left = max(slots - occupied, 0)
                status = str(t.get("status", "")).upper()
                fill_str = f"**{occupied}/{slots} FILLED**" + (
                    " — 🔴 FULL" if left == 0 else f" — {left} slot{'s' if left != 1 else ''} left"
                )
                lines.append(
                    f"**#{t['id']} {t['name']}** — `{status}`\n"
                    f"   {fill_str}\n"
                    f"   starts: {t.get('starts_at') or '—'}"
                )
            embed.add_field(name=f"▸ {mode}", value="\n".join(lines), inline=False)

        embed.set_footer(text="ERVSE · Register with /register in Discord")
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
        embed = discord.Embed(title="🏆 Top 10 — Most Wins",
                              description="\n".join(lines), color=0xFFB000)
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
        embed = discord.Embed(title="🔥 Current Winstreaks — Top 10",
                              description="\n".join(lines), color=0xFFB000)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Matches(bot))
