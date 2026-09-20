import discord
from discord.ext import commands
import random
from utils.duration import parse_duration, format_duration


class GiveawayView(discord.ui.View):
    def __init__(self, duration_seconds, prize, host):
        super().__init__(timeout=duration_seconds)
        self.participants = []
        self.prize = prize
        self.host = host
        self.message = None

    @discord.ui.button(label="Join Giveaway", style=discord.ButtonStyle.green)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user in self.participants:
            await interaction.response.send_message("You already joined!", ephemeral=True)
        else:
            self.participants.append(interaction.user)
            await interaction.response.send_message("✅ Joined successfully!", ephemeral=True)

    async def on_timeout(self):
        if not self.message:
            return
        if not self.participants:
            await self.message.channel.send(f"❌ No participants for **{self.prize}**.")
            return
        winner = random.choice(self.participants)
        await self.message.channel.send(
            f"🎉 Congratulations {winner.mention}! You won **{self.prize}**!"
        )


class Giveaways(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name='giveaway', description='Start a giveaway (e.g. !giveaway 1d Nitro)')
    @commands.has_permissions(administrator=True)
    async def giveaway(self, ctx, duration: str, *, prize: str):
        seconds = parse_duration(duration)
        if seconds is None:
            await ctx.send(
                "❌ Invalid duration. Examples: `1d`, `24hr`, `30m`, `45s`, `1h30m`",
                ephemeral=True
            )
            return

        view = GiveawayView(seconds, prize, ctx.author)
        embed = discord.Embed(
            title="🎁 Giveaway Started!",
            description=(
                f"**Prize:** {prize}\n"
                f"**Duration:** {format_duration(seconds)}\n"
                f"**Hosted by:** {ctx.author.mention}\n\n"
                f"Click the button below to enter!"
            ),
            color=0x00ff00
        )
        message = await ctx.send(embed=embed, view=view)
        view.message = message


async def setup(bot):
    await bot.add_cog(Giveaways(bot))