# cogs/general.py
import discord
from discord.ext import commands
from discord import app_commands
import config
from utils import database as db


class CheckInView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="CHECK IN", style=discord.ButtonStyle.success, emoji="✅",
                       custom_id="ervse_checkin")
    async def checkin(self, interaction: discord.Interaction, button: discord.ui.Button):
        opens = await db.get_user_open_registrations(interaction.user.id)
        if not opens:
            await interaction.response.send_message(
                "❌ You don't have any open tournament registrations.", ephemeral=True
            )
            return

        done = []
        for reg in opens:
            if reg.get("checked_in"):
                continue
            if reg.get("status") not in ("approved", "pending"):
                continue
            try:
                await db.set_registration_checked_in(reg["tournament_id"], interaction.user.id)
                done.append(reg["name"])
            except Exception as e:
                print(f"[checkin] {e}")

        if not done:
            await interaction.response.send_message(
                "ℹ️ You're already checked in (or nothing eligible to check in).",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "✅ Checked in for:\n" + "\n".join(f"• {n}" for n in done),
            ephemeral=True,
        )


class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name='ping', description='Check bot latency')
    async def ping(self, ctx):
        await ctx.send(f'🏓 Pong! Latency: `{round(self.bot.latency * 1000)}ms`')

    @commands.hybrid_command(name='hello', description='Say hello')
    async def hello(self, ctx):
        await ctx.send(f'👋 Hello {ctx.author.mention}!')

    @commands.hybrid_command(name='checkin', description='Check in to your open tournament registrations')
    async def checkin(self, ctx):
        opens = await db.get_user_open_registrations(ctx.author.id)
        if not opens:
            await ctx.send(
                "📭 You have no open tournament registrations. "
                "Use `/register` first, or `/listmatch` to see what's running.",
                ephemeral=True,
            )
            return
        lines = []
        for r in opens:
            tag = "✅ checked in" if r.get("checked_in") else "⏳ not checked in"
            lines.append(f"• **{r['name']}** — {tag}")
        embed = discord.Embed(
            title="🎟️ Check-in",
            description="\n".join(lines) + "\n\nClick below to check in to all open ones.",
            color=0xFFB000,
        )
        await ctx.send(embed=embed, view=CheckInView(self.bot), ephemeral=True)

    # ─── INFOUSER ───
    @commands.hybrid_command(name='infouser', description='[Admin] Full profile of a user')
    @commands.has_permissions(administrator=True)
    @app_commands.describe(about="The user to inspect")
    async def infouser(self, ctx, about: discord.Member):
        target = about

        # Core data
        player = await db.get_player(target.id)
        xp = await db.get_user_xp(target.id)
        wins, losses = await db.get_player_record(target.id)

        # Rank
        rank = None
        try:
            lb = await db.get_global_leaderboard(500)
            for r in lb:
                if r["user_id"] == target.id:
                    rank = r["rank"]; break
        except Exception:
            pass

        ban = await db.get_ban(target.id)
        steam_ban = None
        if player and player.get("steam_id"):
            steam_ban = await db.get_steam_ban(player["steam_id"])

        embed = discord.Embed(
            title=f"🕵️ ERVSE Intel — {target.display_name}",
            color=0xFFB000,
        )
        embed.set_thumbnail(url=target.display_avatar.url)

        embed.add_field(name="Discord", value=f"{target.mention}\n`{target.id}`", inline=False)
        embed.add_field(name="Account Created", value=discord.utils.format_dt(target.created_at, "R"), inline=True)
        embed.add_field(name="Joined Server", value=(discord.utils.format_dt(target.joined_at, "R") if target.joined_at else "—"), inline=True)

        if player:
            embed.add_field(name="Discord Name", value=f"`{player['discord_name'] or '—'}`", inline=True)
            embed.add_field(name="Steam Name",   value=f"`{player['steam_name'] or '—'}`",   inline=True)
            embed.add_field(name="Steam ID64",   value=f"`{player['steam_id'] or '—'}`",     inline=True)
            embed.add_field(name="Verified", value="✅" if player["verified"] else "❌", inline=True)
            embed.add_field(name="Registered", value=f"`{str(player['registered_at'])[:19]}`", inline=True)
        else:
            embed.add_field(name="Registration", value="❌ Not registered", inline=False)

        embed.add_field(
            name="XP / Level / Coins",
            value=f"XP: `{xp['xp']}` · LVL: `{xp['level']}` · 💰 `{xp['coins']}`",
            inline=False,
        )
        embed.add_field(
            name="Record",
            value=f"Wins: **{wins}** · Losses: **{losses}** · Rank: **{('#' + str(rank)) if rank else '—'}**",
            inline=False,
        )

        # Last 5 matches
        try:
            rows = await db.get_match_history(target.id, limit=5)
            if rows:
                lines = []
                for row in rows:
                    match_id, p1, p2, winner_id, score, m_name, m_map, played_at = row
                    opp_id = p2 if p1 == target.id else p1
                    opp = ctx.guild.get_member(opp_id) if ctx.guild else None
                    opp_name = opp.display_name if opp else f"User {opp_id}"
                    res = "🟢 W" if winner_id == target.id else "🔴 L"
                    lines.append(f"{res} vs **{opp_name}** — `{score}` — {str(played_at)[:16]}")
                embed.add_field(name="Last 5 Matches", value="\n".join(lines)[:1024], inline=False)
        except Exception:
            pass

        # Ban status
        if ban:
            embed.add_field(
                name="⛔ Discord Ban",
                value=f"`{ban['reason']}` — by <@{ban['banned_by']}> — {str(ban['banned_at'])[:19]}",
                inline=False,
            )
        if steam_ban:
            embed.add_field(
                name="⛔ Steam Ban",
                value=f"`{steam_ban['reason']}` — Steam `{steam_ban['steam_id']}`",
                inline=False,
            )

        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(General(bot))
