# cogs/voice.py — Join-to-Create temp voice channels + /party commands
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import config
from utils import database as db

# In-memory delay timers for cleanup: {channel_id: asyncio.Task}
_cleanup_tasks: dict[int, asyncio.Task] = {}


class Voice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ─── ON VOICE STATE CHANGE ───
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        try:
            await self._handle_join_to_create(member, before, after)
            await self._handle_temp_vc_cleanup(member, before, after)
        except Exception as e:
            print(f"[voice] on_voice_state_update error: {e}")

    async def _handle_join_to_create(self, member, before, after):
        """When a user joins the designated 'join to create' VC, spawn their private VC."""
        if after.channel is None:
            return
        if after.channel.id != config.JOIN_TO_CREATE_VC_ID:
            return
        if before.channel and before.channel.id == after.channel.id:
            return  # just mute/deaf change, no move

        guild = member.guild
        me = guild.me
        if not me.guild_permissions.manage_channels:
            print("[voice] bot lacks Manage Channels — can't create temp VC")
            return

        # Check if user already owns a live VC
        existing = await db.get_temp_vc_by_owner(member.id)
        if existing:
            ch = guild.get_channel(existing["channel_id"])
            if ch is not None:
                try:
                    await member.move_to(ch, reason="Rejoin existing team VC")
                    return
                except Exception:
                    pass
            # Channel was deleted out-of-band — clean the stale row
            await db.remove_temp_vc(existing["channel_id"])

        # Category — use the source channel's category by default, or config override
        source_cat = after.channel.category
        category = None
        if config.TEMP_VC_CATEGORY_ID:
            cat = guild.get_channel(config.TEMP_VC_CATEGORY_ID)
            if isinstance(cat, discord.CategoryChannel):
                category = cat
        if category is None and source_cat is not None:
            category = source_cat

        # Build permission overwrites
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(connect=False, view_channel=True),
            member: discord.PermissionOverwrite(
                connect=True, speak=True, view_channel=True,
                manage_channels=True, move_members=True, mute_members=True,
                deafen_members=True, stream=True,
            ),
            me: discord.PermissionOverwrite(
                connect=True, manage_channels=True, move_members=True, view_channel=True,
            ),
        }
        if config.STAFF_ROLE_ID:
            staff = guild.get_role(config.STAFF_ROLE_ID)
            if staff:
                overwrites[staff] = discord.PermissionOverwrite(
                    connect=True, view_channel=True, manage_channels=True, move_members=True,
                )

        # Channel name — sanitize (Discord limit: 100 chars)
        safe_name = member.display_name.strip()[:80] or member.name
        channel_name = f"🔊 {safe_name}'s Team"

        try:
            new_ch = await guild.create_voice_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                reason=f"Auto VC for {member}",
            )
        except discord.Forbidden:
            print("[voice] missing permission to create voice channel")
            return
        except Exception as e:
            print(f"[voice] create_voice_channel failed: {e}")
            return

        await db.add_temp_vc(new_ch.id, member.id)

        try:
            await member.move_to(new_ch, reason="Join-to-create")
        except Exception as e:
            print(f"[voice] move_to failed: {e}")

    async def _handle_temp_vc_cleanup(self, member, before, after):
        """Delete temp VCs that become empty (5s grace period to allow reconnects)."""
        if before.channel is None:
            return
        if before.channel.id == after.channel.id if after.channel else False:
            return  # no channel change
        ch = before.channel
        owner_id = await db.get_temp_vc_owner(ch.id)
        if owner_id is None:
            return  # not a temp VC

        # If the channel still has users, nothing to do
        if len(ch.members) > 0:
            # Cancel any pending cleanup for this channel
            task = _cleanup_tasks.pop(ch.id, None)
            if task and not task.done():
                task.cancel()
            return

        # Schedule a delayed delete
        async def delayed_delete(channel_id):
            try:
                await asyncio.sleep(5)
                guild = ch.guild
                target = guild.get_channel(channel_id)
                if target is None:
                    await db.remove_temp_vc(channel_id)
                    _cleanup_tasks.pop(channel_id, None)
                    return
                if len(target.members) > 0:
                    _cleanup_tasks.pop(channel_id, None)
                    return
                try:
                    await target.delete(reason="Temp VC empty — auto cleanup")
                except Exception as e:
                    print(f"[voice] delete failed: {e}")
                await db.remove_temp_vc(channel_id)
            except asyncio.CancelledError:
                pass
            finally:
                _cleanup_tasks.pop(channel_id, None)

        # Cancel previous task if any
        prev = _cleanup_tasks.pop(ch.id, None)
        if prev and not prev.done():
            prev.cancel()
        _cleanup_tasks[ch.id] = asyncio.create_task(delayed_delete(ch.id))

    # ─── /party ───
    party = app_commands.Group(name="party", description="Manage your private team voice channel")

    @party.command(name="invite", description="Invite a user to your private team VC")
    @app_commands.describe(user="The user to invite")
    async def party_invite(self, interaction: discord.Interaction, user: discord.Member):
        await interaction.response.defer(ephemeral=True)

        if user.bot:
            await interaction.followup.send("❌ Can't invite bots to team VCs.", ephemeral=True)
            return

        rec = await db.get_temp_vc_by_owner(interaction.user.id)
        if not rec:
            await interaction.followup.send(
                "❌ You don't own a team voice channel.\n"
                f"Join <#{config.JOIN_TO_CREATE_VC_ID}> to create one.",
                ephemeral=True,
            )
            return

        guild = interaction.guild
        channel = guild.get_channel(rec["channel_id"])
        if channel is None:
            await db.remove_temp_vc(rec["channel_id"])
            await interaction.followup.send("❌ Your team VC no longer exists. Rejoin the hub to create a new one.", ephemeral=True)
            return

        try:
            await channel.set_permissions(
                user,
                connect=True,
                speak=True,
                view_channel=True,
                reason=f"Invited by {interaction.user}",
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ Bot lacks **Manage Channels** to modify permissions.", ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(f"❌ Error: `{e}`", ephemeral=True)
            return

        # If invited user is currently in another voice channel, move them
        moved = False
        if user.voice and user.voice.channel and user.voice.channel.id != channel.id:
            try:
                await user.move_to(channel, reason=f"Party invite from {interaction.user}")
                moved = True
            except Exception as e:
                print(f"[voice] invite move failed: {e}")

        await interaction.followup.send(
            f"✅ Invited {user.mention} to {channel.mention}."
            + (" They were moved in." if moved else " They can join anytime."),
            ephemeral=True,
        )

    @party.command(name="kick", description="Remove a user from your private team VC")
    @app_commands.describe(user="The user to kick")
    async def party_kick(self, interaction: discord.Interaction, user: discord.Member):
        await interaction.response.defer(ephemeral=True)

        rec = await db.get_temp_vc_by_owner(interaction.user.id)
        if not rec:
            await interaction.followup.send(
                f"❌ You don't own a team VC. Join <#{config.JOIN_TO_CREATE_VC_ID}> to create one.",
                ephemeral=True,
            )
            return

        channel = interaction.guild.get_channel(rec["channel_id"])
        if channel is None:
            await db.remove_temp_vc(rec["channel_id"])
            await interaction.followup.send("❌ Your team VC no longer exists.", ephemeral=True)
            return

        if user.id == interaction.user.id:
            await interaction.followup.send("❌ You can't kick yourself.", ephemeral=True)
            return

        try:
            await channel.set_permissions(user, overwrite=None, reason=f"Kicked by {interaction.user}")
        except Exception as e:
            await interaction.followup.send(f"❌ Error: `{e}`", ephemeral=True)
            return

        if user.voice and user.voice.channel and user.voice.channel.id == channel.id:
            try:
                await user.move_to(None, reason="Kicked from team VC")
            except Exception:
                pass

        await interaction.followup.send(f"✅ Removed {user.mention} from your VC.", ephemeral=True)

    @party.command(name="end", description="Close and delete your private team VC")
    async def party_end(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        rec = await db.get_temp_vc_by_owner(interaction.user.id)
        if not rec:
            await interaction.followup.send(
                f"❌ You don't own a team VC. Join <#{config.JOIN_TO_CREATE_VC_ID}> to create one.",
                ephemeral=True,
            )
            return

        channel = interaction.guild.get_channel(rec["channel_id"])
        if channel is None:
            await db.remove_temp_vc(rec["channel_id"])
            await interaction.followup.send("✅ Cleaned up stale VC entry.", ephemeral=True)
            return

        try:
            await channel.delete(reason=f"Party ended by {interaction.user}")
        except Exception as e:
            await interaction.followup.send(f"❌ Could not delete: `{e}`", ephemeral=True)
            return

        await db.remove_temp_vc(rec["channel_id"])
        await interaction.followup.send("✅ Your team VC has been closed.", ephemeral=True)

    @party.command(name="info", description="Show which team VC you own")
    async def party_info(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        rec = await db.get_temp_vc_by_owner(interaction.user.id)
        if not rec:
            await interaction.followup.send(
                f"❌ You don't own a team VC.\n"
                f"Join <#{config.JOIN_TO_CREATE_VC_ID}> to create one.",
                ephemeral=True,
            )
            return
        channel = interaction.guild.get_channel(rec["channel_id"])
        if channel is None:
            await db.remove_temp_vc(rec["channel_id"])
            await interaction.followup.send("❌ Your VC no longer exists — stale entry cleaned.", ephemeral=True)
            return
        await interaction.followup.send(
            f"🎧 Your team VC: {channel.mention}\n"
            f"Members inside: **{len(channel.members)}**",
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(Voice(bot))
