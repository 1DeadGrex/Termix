# cogs/registration.py
import discord
from discord.ext import commands
from discord import app_commands
import os
import config
from utils import database as db


def _is_staff(member: discord.Member) -> bool:
    """True if the member is admin OR has the configured staff role."""
    if member.guild_permissions.administrator:
        return True
    if config.STAFF_ROLE_ID:
        role = member.guild.get_role(config.STAFF_ROLE_ID)
        if role and role in member.roles:
            return True
    return False


class Registration(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ─── REGISTER ───
    @commands.hybrid_command(name='register', description='Register for the tournament (Steam link in DMs)')
    async def register(self, ctx):
        base_url = os.getenv("BASE_URL", "http://localhost:8000")
        link = f"{base_url}/auth/steam?discord_id={ctx.author.id}"

        existing = await db.get_player(ctx.author.id)
        if existing:
            await ctx.send(
                f"⚠️ {ctx.author.mention}, you're already registered. "
                f"Use `/whoami` to see your details.",
                ephemeral=True,
            )
            return

        try:
            await ctx.author.send(
                f"🔗 **Register for the CS2 Tournament**\n\n"
                f"Click this link to link your Steam account:\n{link}\n\n"
                f"Once done, use `/whoami` to verify."
            )
            await ctx.send(f"✅ {ctx.author.mention}, check your DMs!", ephemeral=True)
        except discord.Forbidden:
            await ctx.send(
                f"❌ {ctx.author.mention}, I can't DM you. Please enable "
                f"**Settings → Privacy → Allow DMs from server members**.",
                ephemeral=True,
            )

    # ─── UNREGISTER ───
    @commands.hybrid_command(name='unregister', description='[Staff] Unregister a user')
    @commands.has_permissions(administrator=True)
    async def unregister(self, ctx, member: discord.Member):
        existing = await db.get_player(member.id)
        if not existing:
            await ctx.send(f"❌ {member.mention} is not registered.")
            return
        await db.delete_player(member.id)
        await ctx.send(f"✅ Unregistered {member.mention} (`{member.id}`).")

    # ─── WHOAMI ───
    @commands.hybrid_command(name='whoami', description='Show registration info (IDs are copy-friendly)')
    @app_commands.describe(member="Whose info to look up — staff/admin only for others")
    async def whoami(self, ctx, member: discord.Member = None):
        target = member or ctx.author

        # Non-staff can only view their own info
        if target.id != ctx.author.id and not _is_staff(ctx.author):
            await ctx.send(
                "🚫 You can only view **your own** registration info. "
                "Ask a staff member to look up other operatives.",
                ephemeral=True,
            )
            return

        row = await db.get_player(target.id)

        if not row:
            embed = discord.Embed(
                title=f"❌ {target.display_name} — Not Registered",
                description=(
                    "Run `/register` to start Steam verification, "
                    "or use the Register button on the website."
                ),
                color=0xFF5238,
            )
            embed.add_field(
                name="Discord ID (copy for the website)",
                value=f"`{target.id}`",
                inline=False,
            )
            await ctx.send(embed=embed)
            return

        user_id       = row["user_id"]
        discord_name  = row["discord_name"] or "Unknown"
        steam_id      = row["steam_id"] or "NOT-LINKED"
        verified      = bool(row["verified"])
        registered_at = str(row["registered_at"] or "—")[:19]

        embed = discord.Embed(
            title=f"🎮 {target.display_name}",
            description="Copy the values below and paste them on the website.",
            color=0x00AAFF,
        )
        embed.add_field(name="Discord Username", value=f"`{discord_name}`", inline=False)
        embed.add_field(name="Discord ID", value=f"`{user_id}`", inline=False)
        embed.add_field(name="Steam ID", value=f"`{steam_id}`", inline=False)
        embed.add_field(name="Verified", value="✅ Yes" if verified else "❌ No", inline=True)
        embed.add_field(name="Registered", value=f"`{registered_at}`", inline=True)
        embed.set_footer(text="Long-press a code block to copy • click on desktop")
        embed.set_thumbnail(url=target.display_avatar.url)

        await ctx.send(embed=embed)

    # ─── DEV: FORCE REGISTER ───
    @commands.hybrid_command(name='force_register', description='[DEV] Register without Steam auth')
    @commands.has_permissions(administrator=True)
    async def force_register(self, ctx, steam_id: str = "76561198000000000"):
        await db.add_player(
            user_id=ctx.author.id,
            discord_name=str(ctx.author),
            steam_id=steam_id,
            verified=False,
        )
        await ctx.send(f"✅ [DEV] Registered {ctx.author.mention} with Steam ID `{steam_id}`")


async def setup(bot):
    await bot.add_cog(Registration(bot))
