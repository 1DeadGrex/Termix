import discord
from discord.ext import commands


class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name='ping', description='Check bot latency')
    async def ping(self, ctx):
        latency = round(self.bot.latency * 1000)
        await ctx.send(f'🏓 Pong! Latency: `{latency}ms`')

    @commands.hybrid_command(name='hello', description='Say hello')
    async def hello(self, ctx):
        await ctx.send(f'👋 Hello {ctx.author.mention}!')


async def setup(bot):
    await bot.add_cog(General(bot))