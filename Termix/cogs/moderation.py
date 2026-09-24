# cogs/moderation.py
import discord
from discord.ext import commands
from utils import database as db


class NukeConfirmView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=15)
        self.author_id = author_id
        self.value = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the command author can confirm.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="NUKE", style=discord.ButtonStyle.danger, emoji="💣")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="CANCEL", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        await interaction.response.defer()
        self.stop()


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ─── BANS ───
    @commands.hybrid_command(name='banlist', description='[Staff] View Discord + Steam bans')
    @commands.has_permissions(view_audit_log=True)
    async def banlist(self, ctx):
        embed = discord.Embed(title="🔨 Active Bans", color=0xff0000)

        # Discord bans from our own table
        try:
            rows = await db.get_all_steam_bans(15)
        except Exception:
            rows = []

        if rows:
            lines = []
            for r in rows:
                lines.append(
                    f"`{r['steam_id']}` — {r['reason'] or 'no reason'}\n"
                    f"   linked discord: `{r['linked_discord_id'] or '—'}`"
                )
            embed.add_field(
                name="Steam Bans (recent 15)",
                value="\n".join(lines)[:1020],
                inline=False,
            )
        else:
            embed.add_field(name="Steam Bans", value="None recorded.", inline=False)

        # Discord audit-log view
        audit_lines = []
        try:
            async for entry in ctx.guild.audit_logs(
                limit=10, action=discord.AuditLogAction.ban
            ):
                audit_lines.append(
                    f"{entry.target} — by {entry.user} — {entry.reason or 'no reason'}"
                )
        except Exception:
            pass

        embed.add_field(
            name="Recent Discord Audit Bans (10)",
            value="\n".join(audit_lines)[:1020] if audit_lines else "None.",
            inline=False,
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name='ban_player',
        description='[Staff] Ban a player (Discord + auto-bans their linked Steam ID)'
    )
    @commands.has_permissions(ban_members=True)
    async def ban_player(self, ctx, member: discord.Member, *, reason: str = "No reason"):
        # Try Discord ban (best-effort — record even if already gone)
        try:
            await member.ban(reason=reason)
        except discord.Forbidden:
            await ctx.send("⚠️ Couldn't ban on Discord (missing perms), but recording the ban anyway.")

        await db.add_ban(member.id, reason, ctx.author.id)

        # Report what got banned
        ban_row = await db.get_ban(member.id)
        steam_id = (ban_row or {}).get("steam_id") or ""
        extra = f"\n🔒 Steam ID `{steam_id}` also banned." if steam_id else \
                "\n_(no Steam ID linked — only Discord ban recorded)_"
        await ctx.send(f"🔨 {member.mention} banned. Reason: {reason}{extra}")

    @commands.hybrid_command(name='unban', description='[Staff] Unban a user by Discord ID')
    @commands.has_permissions(ban_members=True)
    async def unban(self, ctx, user_id: int, *, reason: str = "No reason provided"):
        try:
            user = await self.bot.fetch_user(user_id)
        except discord.NotFound:
            user = None

        if user is not None:
            try:
                await ctx.guild.unban(user, reason=reason)
            except discord.NotFound:
                pass
            except discord.Forbidden:
                await ctx.send("❌ I don't have permission to unban members.")
                return
            except Exception as e:
                await ctx.send(f"❌ Error: `{e}`")
                return

        await db.remove_ban(user_id)
        await ctx.send(f"✅ Unbanned **{user or user_id}** (`{user_id}`). Reason: {reason}")

    @commands.hybrid_command(
        name='ban_steam',
        description='[Staff] Ban a Steam ID directly (blocks registration even on new Discord accounts)'
    )
    @commands.has_permissions(ban_members=True)
    async def ban_steam(self, ctx, steam_id: str, *, reason: str = "No reason"):
        steam_id = steam_id.strip()
        if not steam_id.isdigit() or len(steam_id) < 15:
            await ctx.send("❌ That doesn't look like a SteamID64 (should be a long number).")
            return

        # Try to find the linked Discord user (for logging)
        linked = await db.get_player_by_steam_id(steam_id)
        linked_id = linked["user_id"] if linked else 0

        await db.add_steam_ban(steam_id, reason, ctx.author.id, linked_id)
        await ctx.send(
            f"🔒 Steam ID `{steam_id}` banned. Reason: {reason}"
            + (f"\nLinked Discord: <@{linked_id}>" if linked_id else "")
        )

    @commands.hybrid_command(name='unban_steam', description='[Staff] Remove a Steam ban')
    @commands.has_permissions(ban_members=True)
    async def unban_steam(self, ctx, steam_id: str):
        steam_id = steam_id.strip()
        existing = await db.get_steam_ban(steam_id)
        if not existing:
            await ctx.send("❌ That Steam ID isn't banned.")
            return
        await db.remove_steam_ban(steam_id)
        await ctx.send(f"✅ Removed Steam ban for `{steam_id}`.")

    # ─── CHANNEL MANAGEMENT ───
    @commands.hybrid_command(name='lock', description='[Staff] Lock the channel — only staff can talk')
    @commands.has_permissions(manage_channels=True)
    async def lock(self, ctx, channel: discord.TextChannel = None):
        ch = channel or ctx.channel
        overwrite = ch.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = False
        overwrite.add_reactions = False
        try:
            await ch.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        except discord.Forbidden:
            await ctx.send("❌ I don't have **Manage Channels** — can't lock.", ephemeral=True)
            return
        await ch.send("🔒 **Channel locked.** Only staff can speak here now.")
        if ch != ctx.channel:
            await ctx.send(f"🔒 Locked {ch.mention}.", ephemeral=True)

    @commands.hybrid_command(name='unlock', description='[Staff] Unlock the channel — everyone can talk')
    @commands.has_permissions(manage_channels=True)
    async def unlock(self, ctx, channel: discord.TextChannel = None):
        ch = channel or ctx.channel
        overwrite = ch.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = None
        overwrite.add_reactions = None
        try:
            await ch.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        except discord.Forbidden:
            await ctx.send("❌ I don't have **Manage Channels** — can't unlock.", ephemeral=True)
            return
        await ch.send("🔓 **Channel unlocked.** Everyone can speak again.")
        if ch != ctx.channel:
            await ctx.send(f"🔓 Unlocked {ch.mention}.", ephemeral=True)

    # ─── NUKE ───
    @commands.hybrid_command(name='nuke', description='[Staff] Clone the channel and delete the old one')
    @commands.has_permissions(manage_channels=True)
    async def nuke(self, ctx):
        view = NukeConfirmView(ctx.author.id)
        warn = await ctx.send(
            "⚠️ **NUKE CONFIRMATION** — this will delete this channel and create a fresh one. "
            "Click a button within 15s.",
            view=view,
        )
        await view.wait()
        try:
            await warn.delete()
        except Exception:
            pass

        if view.value is not True:
            try:
                await ctx.send("💤 Nuke cancelled.", delete_after=6)
            except Exception:
                pass
            return

        try:
            new_channel = await ctx.channel.clone(reason=f"Nuke by {ctx.author}")
            await new_channel.edit(position=ctx.channel.position)
            await ctx.channel.delete(reason=f"Nuke by {ctx.author}")
            try:
                await new_channel.send("💣 **Channel nuked.** Fresh start.")
            except Exception:
                pass
        except discord.Forbidden:
            try:
                await ctx.send("❌ Missing **Manage Channels** — can't nuke.", delete_after=8)
            except Exception:
                pass
        except Exception as e:
            print(f"[moderation] nuke failed: {e}")
            try:
                await ctx.send(f"❌ Nuke failed: `{type(e).__name__}` — tell staff.", delete_after=8)
            except Exception:
                pass

    # ─── PURGE ───
    @commands.hybrid_command(name='purge', description='[Staff] Delete the last N messages (max 100)')
    @commands.has_permissions(manage_messages=True)
    async def purge(self, ctx, amount: int = 10):
        if amount < 1 or amount > 100:
            await ctx.send("Amount must be 1–100.", ephemeral=True)
            return
        try:
            deleted = await ctx.channel.purge(limit=amount + 1)
            await ctx.send(f"🧹 Deleted {len(deleted) - 1} messages.", delete_after=5)
        except discord.Forbidden:
            await ctx.send("❌ Missing **Manage Messages**.", ephemeral=True)
        except Exception as e:
            await ctx.send(f"❌ Purge failed: `{type(e).__name__}`", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Moderation(bot))
