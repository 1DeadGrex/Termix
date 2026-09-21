# cogs/tickets.py
import discord
from discord.ext import commands
import asyncio
import traceback
import config


class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.red, emoji="🔒")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            # Allow staff OR the ticket opener to close
            is_staff = interaction.user.guild_permissions.manage_channels
            # Check if user is the ticket opener by name pattern
            opener_name = interaction.channel.name.split("-")[1] if "-" in interaction.channel.name else None
            is_opener = opener_name and interaction.user.name.lower() == opener_name

            if not (is_staff or is_opener):
                await interaction.response.send_message(
                    "❌ Only staff or the ticket opener can close this ticket.",
                    ephemeral=True
                )
                return

            await interaction.response.send_message("🔒 Closing ticket in 5 seconds...")
            await asyncio.sleep(5)
            try:
                await interaction.channel.delete(reason="Ticket closed")
            except discord.NotFound:
                pass
        except Exception as e:
            print(f"[tickets] close button error: {e}")
            traceback.print_exc()
            try:
                await interaction.followup.send(f"❌ Error: `{e}`", ephemeral=True)
            except Exception:
                pass


class TicketPanelView(discord.ui.View):
    """The dropdown panel users see."""

    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.select(
        placeholder="Choose a ticket type...",
        options=[
            discord.SelectOption(label="General Support", value="support",
                                 description="Get help from staff", emoji="🛠️"),
            discord.SelectOption(label="Report a Player", value="report",
                                 description="Report a rule breaker", emoji="🚨"),
            discord.SelectOption(label="Ban Appeal", value="appeal",
                                 description="Appeal your ban", emoji="⚖️"),
            discord.SelectOption(label="Other", value="other",
                                 description="Anything else", emoji="❓"),
        ]
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        # ── Step 1: defer so Discord doesn't timeout ──
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
        except Exception as e:
            print(f"[tickets] defer failed: {e}")
            return

        # ── Step 2: everything else wrapped in try/except ──
        try:
            guild = interaction.guild
            user = interaction.user
            ticket_type = select.values[0]

            print(f"[tickets] {user} requested {ticket_type} ticket in {guild.name}")

            # ── Sanity checks ──
            if guild is None:
                await interaction.followup.send("❌ This can only be used in a server.", ephemeral=True)
                return

            # ── Check bot permissions ──
            me = guild.me
            if not me.guild_permissions.manage_channels:
                await interaction.followup.send(
                    "❌ I don't have the **Manage Channels** permission. "
                    "Please ask an admin to grant it.",
                    ephemeral=True
                )
                return

            # ── Prevent duplicate tickets ──
            channel_name = f"ticket-{user.name.lower()}-{ticket_type}".replace(" ", "-")[:100]
            existing = discord.utils.find(
                lambda c: c.name == channel_name,
                guild.text_channels
            )
            if existing:
                await interaction.followup.send(
                    f"⚠️ You already have an open ticket: {existing.mention}",
                    ephemeral=True
                )
                return

            # ── Resolve category (validate it's really a CategoryChannel) ──
            category = None
            if config.TICKET_CATEGORY_ID:
                cat = guild.get_channel(config.TICKET_CATEGORY_ID)
                if isinstance(cat, discord.CategoryChannel):
                    category = cat
                else:
                    print(f"[tickets] WARNING: TICKET_CATEGORY_ID={config.TICKET_CATEGORY_ID} "
                          f"is not a CategoryChannel (got {type(cat).__name__}). Creating at top level.")

            # ── Resolve staff role ──
            staff_role = None
            if config.STAFF_ROLE_ID:
                staff_role = guild.get_role(config.STAFF_ROLE_ID)
                if staff_role is None:
                    print(f"[tickets] WARNING: STAFF_ROLE_ID={config.STAFF_ROLE_ID} not found.")

            # ── Build permission overwrites ──
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                user: discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True,
                    attach_files=True,
                    embed_links=True,
                    read_message_history=True,
                ),
                me: discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True,
                    manage_channels=True,
                    manage_messages=True,
                ),
            }
            if staff_role:
                overwrites[staff_role] = discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True,
                    manage_messages=True,
                    attach_files=True,
                    embed_links=True,
                )

            # ── Create the channel ──
            try:
                channel = await guild.create_text_channel(
                    name=channel_name,
                    category=category,
                    overwrites=overwrites,
                    topic=f"{config.TICKET_TYPES.get(ticket_type, ticket_type)} | "
                          f"Opened by {user} ({user.id})"[:1024]
                )
            except discord.Forbidden as e:
                print(f"[tickets] Forbidden: {e}")
                await interaction.followup.send(
                    "❌ I don't have permission to create channels. "
                    "Check that my role is above the category's permissions and has **Manage Channels**.",
                    ephemeral=True
                )
                return
            except discord.HTTPException as e:
                print(f"[tickets] HTTPException creating channel: {e}")
                await interaction.followup.send(
                    f"❌ Discord rejected the channel creation: `{e.text if hasattr(e, 'text') else e}`",
                    ephemeral=True
                )
                return

            print(f"[tickets] Created channel {channel.name} ({channel.id})")

            # ── Welcome message inside the ticket ──
            try:
                embed = discord.Embed(
                    title=config.TICKET_TYPES.get(ticket_type, ticket_type),
                    description=(
                        f"Hi {user.mention}, staff will be with you shortly.\n\n"
                        f"Please describe your issue in detail. If reporting someone, "
                        f"include **proof** (screenshots, clips, IDs)."
                    ),
                    color=0x5865F2
                )
                embed.set_footer(text="Click the lock button below when your issue is resolved.")
                await channel.send(embed=embed, view=TicketCloseView())

                # Ping staff if the role exists
                if staff_role:
                    await channel.send(f"{staff_role.mention} — new ticket from {user.mention}")
            except Exception as e:
                print(f"[tickets] Failed to send welcome message: {e}")
                # Channel was still created, so still tell the user

            # ── Confirm to the user ──
            await interaction.followup.send(
                f"✅ Ticket created: {channel.mention}",
                ephemeral=True
            )

        except Exception as e:
            # ── LAST RESORT: always respond so the spinner stops ──
            print(f"[tickets] UNCAUGHT ERROR in select_callback: {e}")
            traceback.print_exc()
            try:
                await interaction.followup.send(
                    f"❌ Unexpected error while creating ticket:\n```\n{type(e).__name__}: {e}\n```",
                    ephemeral=True
                )
            except Exception as inner:
                print(f"[tickets] Could not send error followup: {inner}")


class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name='setup_tickets', description='[Admin] Post the ticket panel in this channel')
    @commands.has_permissions(administrator=True)
    async def setup_tickets(self, ctx):
        embed = discord.Embed(
            title="🎫 Support Tickets",
            description=(
                "Need help? Pick a category below to open a private ticket.\n\n"
                "🛠️ **General Support** — questions, help\n"
                "🚨 **Report a Player** — report rule breakers with proof\n"
                "⚖️ **Ban Appeal** — appeal a ban\n"
                "❓ **Other** — anything else"
            ),
            color=0x5865F2
        )
        await ctx.send(embed=embed, view=TicketPanelView(self.bot))

    @commands.hybrid_command(name='ticket', description='Open a support ticket')
    async def ticket(self, ctx, ticket_type: str):
        valid = {"support", "report", "appeal", "other"}
        if ticket_type.lower() not in valid:
            await ctx.send(f"❌ Valid types: {', '.join(valid)}")
            return
        await ctx.send(
            f"👉 Please use the ticket panel in <#{ctx.channel.id}> to open a **{ticket_type}** ticket.",
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(Tickets(bot))
