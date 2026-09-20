import discord
from discord.ext import commands
import os
from utils import database as db


class Registration(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ─── REGISTER ───
    @commands.hybrid_command(name='register', description='Register for the tournament (Steam link in DMs)')
    async def register(self, ctx):
        base_url = os.getenv("BASE_URL", "http://localhost:8000")
        link = f"{base_url}/auth/steam?discord_id={ctx.author.id}"

        # Check if already registered
        existing = await db.get_player(ctx.author.id)
        if existing:
            await ctx.send(
                f"⚠️ {ctx.author.mention}, you're already registered. "
                f"Use `/whoami` to see your details, or contact staff to change it.",
                ephemeral=True
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
                ephemeral=True
            )

    # ─── UNREGISTER (Staff only) ───
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
    @commands.hybrid_command(name='whoami', description='Show your registration status')
    async def whoami(self, ctx, member: discord.Member = None):
        target = member or ctx.author
        row = await db.get_player(target.id)

        if not row:
            await ctx.send(f"❌ {target.mention} is not registered. Use `/register`.")
            return

        user_id, discord_name, steam_id, verified, registered_at = row
        embed = discord.Embed(
            title=f"🎮 {target.display_name}",
            color=0x00aaff
        )
        embed.add_field(name="Discord ID", value=f"`{user_id}`", inline=False)
        embed.add_field(name="Steam ID", value=f"`{steam_id}`", inline=True)
        embed.add_field(name="Verified", value="✅ Yes" if verified else "❌ No", inline=True)
        embed.add_field(name="Registered", value=str(registered_at), inline=False)
        embed.set_thumbnail(url=target.display_avatar.url)
        await ctx.send(embed=embed)

    # ─── DEV ONLY: fake register for testing ───
    @commands.hybrid_command(name='force_register', description='[DEV] Register without Steam auth')
    @commands.has_permissions(administrator=True)
    async def force_register(self, ctx, steam_id: str = "76561198000000000"):
        await db.add_player(
            user_id=ctx.author.id,
            discord_name=str(ctx.author),
            steam_id=steam_id,
            verified=False
        )
        await ctx.send(f"✅ [DEV] Registered {ctx.author.mention} with Steam ID `{steam_id}`")


async def setup(bot):
    await bot.add_cog(Registration(bot))