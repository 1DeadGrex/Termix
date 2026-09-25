# cogs/moderation.py
import discord
from discord.ext import commands, tasks
import asyncio
import config
from utils import database as db


class NukeConfirmView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=15)
        self.author_id = author_id
        self.value = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Only the author can confirm.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="NUKE", style=discord.ButtonStyle.danger, emoji="💣")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        await interaction.response.defer(); self.stop()

    @discord.ui.button(label="CANCEL", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        await interaction.response.defer(); self.stop()


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ─── CATCHER ───
    @commands.hybrid_command(
        name='setup_catcher',
        description='[Admin] Trap channel — posting here nukes the user\'s last 12h of messages everywhere'
    )
    @commands.has_permissions(administrator=True)
    async def setup_catcher(self, ctx):
        await db.add_catcher_channel(ctx.channel.id, ctx.guild.id, ctx.author.id)
        await ctx.send(
            "🪤 **Catcher armed.**\n"
            "Any non-staff message posted in this channel will:\n"
            "• Delete **all of that user's messages in the last 12 hours** across every channel\n"
            "• DM them a warning\n"
            "• Alert this channel\n\n"
            "Run `/setup_catcher` again to disarm? No — this stays armed until you delete the channel "
            "or remove the entry from the DB. (Contact staff for a disarm command.)",
            ephemeral=True,
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if message.content.startswith(("!", "/", ".", "?")):
            return
        # Only trigger in a catcher channel
        try:
            if not await db.is_catcher_channel(message.channel.id):
                return
        except Exception as e:
            print(f"[catcher] check failed: {e}")
            return

        # Staff bypass
        author = message.author
        if isinstance(author, discord.Member):
            if author.guild_permissions.administrator:
                return
            if config.STAFF_ROLE_ID:
                role = message.guild.get_role(config.STAFF_ROLE_ID)
                if role and role in author.roles:
                    return

        # Trigger!
        guild = message.guild
        now = discord.utils.utcnow()
        cutoff = now.timestamp() - 12 * 3600  # 12 hours ago

        deleted_count = 0
        # 1) Delete the trap message itself
        try:
            await message.delete()
        except Exception:
            pass

        # 2) Purge user's messages from all text channels in the last 12 hours
        for ch in guild.text_channels:
            # Skip channels we can't read/manage
            try:
                perms = ch.permissions_for(guild.me)
                if not perms.read_message_history or not perms.manage_messages:
                    continue
            except Exception:
                continue

            to_delete = []
            try:
                async for m in ch.history(limit=500, after=discord.Object(id=int(cutoff * 1000))):
                    if m.author.id == author.id:
                        to_delete.append(m)
            except Exception as e:
                print(f"[catcher] history scan failed in #{ch.name}: {e}")
                continue

            for m in to_delete:
                try:
                    await m.delete()
                    deleted_count += 1
                except Exception:
                    pass
                if deleted_count % 5 == 0:
                    await asyncio.sleep(0.3)
            # brief pause between channels
            await asyncio.sleep(0.4)

        # 3) DM the user
        try:
            embed = discord.Embed(
                title="⚠️ ERVSE Security Alert",
                description=(
                    f"A message was posted from your account in a channel you shouldn't be using. "
                    f"**{deleted_count} messages** from the last 12 hours have been removed for "
                    f"security.\n\nIf **this wasn't you**, your account may be compromised. "
                    f"Change your password and enable 2FA immediately."
                ),
                color=0xFF5238,
            )
            await author.send(embed=embed)
        except Exception as e:
            print(f"[catcher] DM failed: {e}")

        # 4) Alert in the catcher channel
        try:
            alert = discord.Embed(
                title="🪤 CATCHER TRIGGERED",
                description=(
                    f"**User:** {author.mention} (`{author.id}`)\n"
                    f"**Action:** Deleted **{deleted_count}** messages from the last 12h"
                ),
                color=0xFF5238,
                timestamp=now,
            )
            await message.channel.send(embed=alert)
        except Exception:
            pass

    # ─── BANS ───
    @commands.hybrid_command(name='banlist', description='[Staff] View Discord + Steam bans')
    @commands.has_permissions(view_audit_log=True)
    async def banlist(self, ctx):
        embed = discord.Embed(title="🔨 Active Bans", color=0xff0000)
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
            embed.add_field(name="Steam Bans (recent 15)",
                            value="\n".join(lines)[:1020], inline=False)
        else:
            embed.add_field(name="Steam Bans", value="None recorded.", inline=False)
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name='ban_player',
        description='[Staff] Ban a player (Discord + auto-bans their linked Steam ID)'
    )
    @commands.has_permissions(ban_members=True)
    async def ban_player(self, ctx, member: discord.Member, *, reason: str = "No reason"):
        try:
            await member.ban(reason=reason)
        except discord.Forbidden:
            await ctx.send("⚠️ Couldn't ban on Discord (missing perms), but recording anyway.")
        await db.add_ban(member.id, reason, ctx.author.id)
        ban_row = await db.get_ban(member.id)
        steam_id = (ban_row or {}).get("steam_id") or ""
        extra = f"\n🔒 Steam `{steam_id}` also banned." if steam_id else \
                "\n_(no Steam ID linked — Discord only)_"
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
                await ctx.send("❌ Missing permission to unban."); return
        await db.remove_ban(user_id)
        await ctx.send(f"✅ Unbanned **{user or user_id}** (`{user_id}`). Reason: {reason}")

    @commands.hybrid_command(
        name='ban_steam',
        description='[Staff] Ban a Steam ID directly (blocks new Discord accounts too)'
    )
    @commands.has_permissions(ban_members=True)
    async def ban_steam(self, ctx, steam_id: str, *, reason: str = "No reason"):
        steam_id = steam_id.strip()
        if not steam_id.isdigit() or len(steam_id) < 15:
            await ctx.send("❌ That's not a SteamID64.")
            return
        linked = await db.get_player_by_steam_id(steam_id)
        linked_id = linked["user_id"] if linked else 0
        await db.add_steam_ban(steam_id, reason, ctx.author.id, linked_id)
        await ctx.send(
            f"🔒 Steam `{steam_id}` banned. Reason: {reason}"
            + (f"\nLinked Discord: <@{linked_id}>" if linked_id else "")
        )

    @commands.hybrid_command(name='unban_steam', description='[Staff] Remove a Steam ban')
    @commands.has_permissions(ban_members=True)
    async def unban_steam(self, ctx, steam_id: str):
        steam_id = steam_id.strip()
        existing = await db.get_steam_ban(steam_id)
        if not existing:
            await ctx.send("❌ That Steam ID isn't banned."); return
        await db.remove_steam_ban(steam_id)
        await ctx.send(f"✅ Removed Steam ban for `{steam_id}`.")

    # ─── LOCK / UNLOCK ───
    @commands.hybrid_command(name='lock', description='[Staff] Lock the channel')
    @commands.has_permissions(manage_channels=True)
    async def lock(self, ctx, channel: discord.TextChannel = None):
        ch = channel or ctx.channel
        overwrite = ch.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = False
        overwrite.add_reactions = False
        try:
            await ch.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        except discord.Forbidden:
            await ctx.send("❌ Missing **Manage Channels**.", ephemeral=True); return
        await ch.send("🔒 **Channel locked.**")

    @commands.hybrid_command(name='unlock', description='[Staff] Unlock the channel')
    @commands.has_permissions(manage_channels=True)
    async def unlock(self, ctx, channel: discord.TextChannel = None):
        ch = channel or ctx.channel
        overwrite = ch.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = None
        overwrite.add_reactions = None
        try:
            await ch.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        except discord.Forbidden:
            await ctx.send("❌ Missing **Manage Channels**.", ephemeral=True); return
        await ch.send("🔓 **Channel unlocked.**")

    # ─── NUKE ───
    @commands.hybrid_command(name='nuke', description='[Staff] Clone the channel')
    @commands.has_permissions(manage_channels=True)
    async def nuke(self, ctx):
        view = NukeConfirmView(ctx.author.id)
        warn = await ctx.send("⚠️ **NUKE?** Confirm within 15s.", view=view)
        await view.wait()
        try: await warn.delete()
        except Exception: pass
        if view.value is not True:
            try: await ctx.send("💤 Nuke cancelled.", delete_after=6)
            except Exception: pass
            return
        try:
            new_channel = await ctx.channel.clone(reason=f"Nuke by {ctx.author}")
            await new_channel.edit(position=ctx.channel.position)
            await ctx.channel.delete(reason=f"Nuke by {ctx.author}")
            try: await new_channel.send("
