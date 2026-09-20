import discord
from discord.ext import commands
import asyncio
import config


class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.red, emoji="🔒")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_channels:
            # Allow opener too
            if interaction.channel.name.startswith("ticket-"):
                pass
            else:
                await interaction.response.send_message("❌ Only staff can close tickets.", ephemeral=True)
                return

        await interaction.response.send_message("🔒 Closing ticket in 5 seconds...")
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete(reason="Ticket closed")
        except discord.NotFound:
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
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        user = interaction.user
        ticket_type = select.values[0]

        # Prevent duplicate tickets per user per type
        existing = discord.utils.find(
            lambda c: c.name == f"ticket-{user.name.lower()}-{ticket_type}",
            guild.text_channels
        )
        if existing:
            await interaction.followup.send(
                f"⚠️ You already have an open {ticket_type} ticket: {existing.mention}",
                ephemeral=True
            )
            return

        # Find or create the ticket category
        category = None
        if config.TICKET_CATEGORY_ID:
            category = guild.get_channel(config.TICKET_CATEGORY_ID)

        # Build permission overwrites
        staff_role = guild.get_role(config.STAFF_ROLE_ID) if config.STAFF_ROLE_ID else None
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(
                read_messages=True, send_messages=True, manage_messages=True
            )

        # Create the ticket channel
        try:
            channel = await guild.create_text_channel(
                name=f"ticket-{user.name.lower()}-{ticket_type}",
                category=category,
                overwrites=overwrites,
                topic=f"{config.TICKET_TYPES.get(ticket_type, ticket_type)} | Opened by {user} ({user.id})"
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ I don't have permission to create channels. Ask an admin to check my permissions.",
                ephemeral=True
            )
            return

        # Welcome message inside the ticket
        embed = discord.Embed(
            title=f"{config.TICKET_TYPES.get(ticket_type, ticket_type)}",
            description=(
                f"Hi {user.mention}, staff will be with you shortly.\n\n"
                f"Please describe your issue in detail. If reporting someone, "
                f"include **proof** (screenshots, clips, IDs)."
            ),
            color=0x5865F2
        )
        embed.set_footer(text="Click the lock button below when your issue is resolved.")
        await channel.send(embed=embed, view=TicketCloseView())

        # Ping staff
        if staff_role:
            await channel.send(f"{staff_role.mention} — new ticket from {user.mention}")

        await interaction.followup.send(
            f"✅ Ticket created: {channel.mention}",
            ephemeral=True
        )


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

    # ─── Manual slash command to open ticket (in case user prefers it) ───
    @commands.hybrid_command(name='ticket', description='Open a support ticket')
    async def ticket(self, ctx, ticket_type: str):
        mapping = {
            "support": "support",
            "report": "report",
            "appeal": "appeal",
            "other": "other",
        }
        if ticket_type.lower() not in mapping:
            await ctx.send("❌ Valid types: `support`, `report`, `appeal`, `other`")
            return
        await ctx.send(
            f"👉 Please use the ticket panel to open a **{ticket_type}** ticket "
            f"(it prevents duplicates and pings staff automatically).",
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(Tickets(bot))