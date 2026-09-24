# cogs/announcements.py
import discord
from discord.ext import commands
import config


class Announcements(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name='announce', description='[Admin] Send a tournament announcement')
    @commands.has_permissions(administrator=True)
    async def announce(self, ctx, *, message: str):
        embed = discord.Embed(
            title="📢 Tournament Announcement",
            description=message,
            color=0xff0000,
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text=f"Posted by {ctx.author}")

        # Try to post in the configured announce channel; fall back to current channel
        ch_id = getattr(config, "ANNOUNCE_CHANNEL_ID", 0) or 0
        target = None
        if ch_id:
            target = ctx.guild.get_channel(ch_id)
            if target is None:
                try:
                    target = await self.bot.fetch_channel(ch_id)
                except Exception:
                    target = None

        if target and target.id != ctx.channel.id:
            try:
                await target.send(embed=embed)
                await ctx.send(f"✅ Posted to {target.mention}.", ephemeral=True)
                return
            except Exception as e:
                await ctx.send(f"⚠️ Couldn't post to announce channel: `{e}` — posting here instead.",
                               ephemeral=True)

        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Announcements(bot))
