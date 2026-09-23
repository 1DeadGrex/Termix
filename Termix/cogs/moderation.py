# cogs/moderation.py
import discord
from discord.ext import commands
import asyncio
import aiosqlite  # kept for backwards-compat imports, not used here
from utils import database as db


class NukeConfirmView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=15)
        self.author_id = author_id
        self.value = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Only the command author can confirm.", ephemeral=True)
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
    @commands.hybrid_command(name='banlist', description='[Staff] View recent ban history')
    @commands.has_permissions(view_audit_log=True)
    async def banlist(self, ctx):
        embed = discord.Embed(title="🔨 Ban History", color=0xff0000)
        count = 0
        async for entry in ctx.guild.audit_logs(limit=20, action=discord.AuditLogAction.ban):
            embed.add_field(
                name=f"{entry.target}",
                value=f"Banned by: {entry.user}\nReason: {entry.reason or 'No reason'}",
                inline=False,
            )
            count += 1
        if count == 0:
            embed.description = "No bans recorded."
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='ban_player', description='[Staff] Ban a player and log it')
    @commands.has_permissions(ban_members=True)
    async def ban_player(self, ctx, member: discord.Member, *, reason: str = "No reason"):
        await member.ban(reason=reason)
        await db.add_ban(member.id, reason, ctx.author.id)
        await ctx.send(f"🔨 {member.mention} banned. Reason: {reason}")

    @commands.hybrid_command(name='unban', description='[Staff] Unban a user by ID')
    @commands.has_permissions(ban_members=True)
    async def unban(self, ctx, user_id: int, *, reason: str = "No reason provided"):
        try:
            user = await self.bot.fetch_user(user_id)
            await ctx.guild.unban(user, reason=reason)
        except discord.NotFound:
            await ctx.send("❌ That user isn't banned or doesn't exist.")
            return
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to unban members.")
            return
        except Exception as e:
            await ctx.send(f"❌ Error: `{e}`")
            return
        await db.remove_ban(user_id)
        await ctx.send(f"✅ Unbanned **{user}** (`{user_id}`). Reason: {reason}")

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
            "React below within 15s.",
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

        # Clone with same permissions, position, topic
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
            msg = await ctx.send(f"🧹 Deleted {len(deleted) - 1} messages.", delete_after=5)
        except discord.Forbidden:
            await ctx.send("❌ Missing **Manage Messages**.", ephemeral=True)
        except Exception as e:
            await ctx.send(f"❌ Purge failed: `{type(e).__name__}`", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Moderation(bot))
