# cogs/server_info.py
import discord
from discord.ext import commands


class ServerInfo(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name='serverinfo', description='Show server info')
    async def serverinfo(self, ctx):
        guild = ctx.guild
        if guild is None:
            await ctx.send("❌ This command only works in a server.", ephemeral=True)
            return

        owner = guild.owner
        if owner is None:
            try:
                owner = await guild.fetch_owner()
            except Exception:
                owner = None

        embed = discord.Embed(title=f"📊 {guild.name}", color=0x00aaff)
        embed.add_field(name="Members", value=str(guild.member_count), inline=True)
        embed.add_field(name="Owner", value=owner.mention if owner else "Unknown", inline=True)
        embed.add_field(name="Created", value=guild.created_at.strftime("%Y-%m-%d"), inline=True)
        embed.add_field(name="Channels", value=str(len(guild.channels)), inline=True)
        embed.add_field(name="Roles", value=str(len(guild.roles)), inline=True)
        embed.add_field(name="Boosts", value=f"{guild.premium_subscription_count} (Tier {guild.premium_tier})", inline=True)
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(ServerInfo(bot))
