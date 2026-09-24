# cogs/tickets.py
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import traceback
import config


class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.red, emoji="🔒")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.send_message("🔒 Closing in 5s…")
            await asyncio.sleep(5)
            await interaction.channel.delete(reason="Ticket closed")
        except discord.NotFound:
            pass
        except Exception as e:
            print(f"[tickets] close failed: {e}")


async def _create_ticket_channel(guild: discord.Guild, user: discord.Member, ticket_type: str):
    """Create a private ticket channel. Raises PermissionError with a user-friendly message."""
    if guild is None:
        raise PermissionError("This can only be used in a server.")

    me = guild.me
    if not me.guild_permissions.manage_channels:
        raise PermissionError("Bot missing **Manage Channels** — ask an admin.")

    channel_name = f"ticket-{user.name.lower()}-{ticket_type}".replace(" ", "-")[:100]
    existing = discord.utils.find(lambda c: c.name == channel_name, guild.text_channels)
    if existing:
        raise PermissionError(f"You already have a ticket open: {existing.mention}")

    category = None
    if config.TICKET_CATEGORY_ID:
        cat = guild.get_channel(config.TICKET_CATEGORY_ID)
        if isinstance(cat, discord.CategoryChannel):
            category = cat

    staff_role = None
    if config.STAFF_ROLE_ID:
        staff_role = guild.get_role(config.STAFF_ROLE_ID)

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        user: discord.PermissionOverwrite(
            read_messages=True, send_messages=True,
            attach_files=True, embed_links=True, read_message_history=True,
        ),
        me: discord.PermissionOverwrite(
            read_messages=True, send_messages=True,
            manage_channels=True, manage_messages=True,
        ),
    }
    if staff_role:
        overwrites[staff_role] = discord.PermissionOverwrite(
            read_messages=True, send_messages=True, manage_messages=True,
        )

    try:
        channel = await guild.create_text_channel(
            name=channel_name, category=category, overwrites=overwrites,
            topic=f"{config.TICKET_TYPES.get(ticket_type, ticket_type)} | Opened by {user} ({user.id})"[:1024],
        )
    except discord.Forbidden:
        raise PermissionError("Bot doesn't have permission to create channels.")
    except discord.HTTPException as e:
        raise PermissionError(f"Discord rejected creation: {e}")

    embed = discord.Embed(
        title=config.TICKET_TYPES.get(ticket_type, ticket_type),
        description=(
            f"Hi {user.mention}, staff will be with you shortly.\n\n"
            f"Describe your issue in detail. If reporting someone, include **proof** "
            f"(screenshots, clips, IDs)."
        ),
        color=0x5865F2,
    )
    embed.set_footer(text="Click the lock button below when resolved.")
    try:
        await channel.send(embed=embed, view=TicketCloseView())
        if staff_role:
            await channel.send(f"{staff_role.mention} — new ticket from {user.mention}")
    except Exception as e:
        print(f"[tickets] welcome message failed: {e}")
    return channel


class TicketPanelView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.select(
        placeholder="Choose a ticket type…",
        options=[
            discord.SelectOption(label="General Support", value="support", description="Get help from staff", emoji="🛠️"),
            discord.SelectOption(label="Report a Player", value="report", description="Report a rule breaker", emoji="🚨"),
            discord.SelectOption(label="Ban Appeal", value="appeal", description="Appeal a ban", emoji="⚖️"),
            discord.SelectOption(label="Other", value="other", description="Anything else", emoji="❓"),
        ],
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
        except Exception:
            return
        try:
            channel = await _create_ticket_channel(interaction.guild, interaction.user, select.values[0])
            await interaction.followup.send(f"✅ Ticket created: {channel.mention}", ephemeral=True)
        except PermissionError as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)
        except Exception as e:
            print(f"[tickets] select_callback error: {e}")
            traceback.print_exc()
            try:
                await interaction.followup.send(
                    f"❌ Unexpected error: `{type(e).__name__}` — tell staff.",
                    ephemeral=True,
                )
            except Exception:
                pass


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
            color=0x5865F2,
        )
        await ctx.send(embed=embed, view=TicketPanelView(self.bot))

    @commands.hybrid_command(name='ticket', description='Open a support ticket in this channel')
    @app_commands.describe(ticket_type="Pick a ticket type — support, report, appeal, or other")
    @app_commands.choices(ticket_type=[
        app_commands.Choice(name="🛠️ General Support", value="support"),
        app_commands.Choice(name="🚨 Report a Player", value="report"),
        app_commands.Choice(name="⚖️ Ban Appeal", value="appeal"),
        app_commands.Choice(name="❓ Other", value="other"),
    ])
    async def ticket(self, ctx, ticket_type: app_commands.Choice[str] = None):
        if ticket_type is None:
            await ctx.send(
                "**Open a ticket** — available types:\n"
                "• 🛠️ **support** — General Support\n"
                "• 🚨 **report** — Report a Player\n"
                "• ⚖️ **appeal** — Ban Appeal\n"
                "• ❓ **other** — Anything else\n\n"
                f"Run `/ticket <type>` here to open one instantly, "
                f"or use the ticket panel in <#{config.SUPPORT_CHANNEL_ID or 'the support channel'}>.",
                ephemeral=True,
            )
            return

        try:
            channel = await _create_ticket_channel(ctx.guild, ctx.author, ticket_type.value)
            await ctx.send(f"✅ Ticket created: {channel.mention}", ephemeral=True)
        except PermissionError as e:
            await ctx.send(
                f"⚠️ Couldn't create the ticket here: {e}\n"
                f"Please use the ticket panel in <#{config.SUPPORT_CHANNEL_ID}>.",
                ephemeral=True,
            )
        except Exception as e:
            print(f"[tickets] /ticket failed: {e}")
            traceback.print_exc()
            await ctx.send(
                f"❌ Something went wrong opening the ticket. Please try the panel in "
                f"<#{config.SUPPORT_CHANNEL_ID}> or tell staff.",
                ephemeral=True,
            )


async def setup(bot):
    await bot.add_cog(Tickets(bot))
