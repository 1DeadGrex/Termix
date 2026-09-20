import discord
from discord.ext import commands, tasks

ANNOUNCE_CHANNEL_ID = 1234567890  # ← put your channel ID here

class Announcements(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name='announce', description='Send a tournament announcement')
    @commands.has_permissions(administrator=True)
    async def announce(self, ctx, *, message: str):
        embed = discord.Embed(
            title="📢 Tournament Announcement",
            description=message,
            color=0xff0000,
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text=f"Posted by {ctx.author}")
        await ctx.send(embed=embed)

    # Example: auto-announce every 30 min (disabled by default — uncomment to enable)
    # @tasks.loop(minutes=30)
    # async def auto_announce(self):
    #     channel = self.bot.get_channel(ANNOUNCE_CHANNEL_ID)
    #     if channel:
    #         await channel.send("⏰ Reminder: Tournament check-in closes in 30 minutes!")

    # @commands.Cog.listener()
    # async def on_ready(self):
    #     if not self.auto_announce.is_running():
    #         self.auto_announce.start()


async def setup(bot):
    await bot.add_cog(Announcements(bot))