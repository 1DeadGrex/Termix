import discord
from discord.ext import commands
import config

# In-memory state: {guild_id: {"last_number": int, "last_user": int | None}}
counting_state = {}


class Counting(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        # Ignore bots, DMs, and channels that aren't the counting channel
        if message.author.bot or not message.guild:
            return
        if config.COUNTING_CHANNEL_ID == 0:
            return  # not configured yet
        if message.channel.id != config.COUNTING_CHANNEL_ID:
            return

        guild_id = message.guild.id
        state = counting_state.setdefault(guild_id, {"last_number": 0, "last_user": None})

        # Same user counted twice in a row
        if state["last_user"] == message.author.id:
            try:
                await message.add_reaction("❌")
            except discord.Forbidden:
                pass
            return

        # Must be a valid number
        try:
            number = int(message.content.strip())
        except ValueError:
            try:
                await message.add_reaction("❌")
            except discord.Forbidden:
                pass
            return

        # Must be the next number
        if number == state["last_number"] + 1:
            state["last_number"] = number
            state["last_user"] = message.author.id
            try:
                await message.add_reaction("✅")
            except discord.Forbidden:
                pass
        else:
            # Wrong number — reset
            try:
                await message.add_reaction("❌")
                await message.channel.send(
                    f"💥 {message.author.mention} broke the chain at **{state['last_number']}**! "
                    f"Restart from **1**."
                )
            except discord.Forbidden:
                pass
            state["last_number"] = 0
            state["last_user"] = None

    # ─── ADMIN: set channel without restarting ───
    @commands.hybrid_command(name='set_counting_channel', description='[Admin] Set this channel as counting channel')
    @commands.has_permissions(administrator=True)
    async def set_counting_channel(self, ctx):
        config.COUNTING_CHANNEL_ID = ctx.channel.id
        counting_state.clear()
        await ctx.send(f"✅ Counting channel set to {ctx.channel.mention}. Starting from 1.")

    # ─── ADMIN: reset the count ───
    @commands.hybrid_command(name='reset_counting', description='[Admin] Reset counting for this server')
    @commands.has_permissions(administrator=True)
    async def reset_counting(self, ctx):
        counting_state[ctx.guild.id] = {"last_number": 0, "last_user": None}
        await ctx.send("🔄 Counting reset. Next number is **1**.")


async def setup(bot):
    await bot.add_cog(Counting(bot))