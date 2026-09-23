# cogs/welcome.py
import discord
from discord.ext import commands
from discord import app_commands
from utils import database as db

SETTING_MSG_KEY = "welcome_message"
SETTING_CH_KEY = "welcome_channel_id"


class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(
        name='setup_welcome',
        description='[Admin] Set the welcome message for new members'
    )
    @commands.has_permissions(administrator=True)
    @app_commands.describe(message="The message to send when someone joins. Supports {user}, {user_name}, {server}, {count}.")
    async def setup_welcome(self, ctx, *, message: str):
        await db.set_setting(SETTING_MSG_KEY, message)
        await db.set_setting(SETTING_CH_KEY, str(ctx.channel.id))
        preview = (
            message
            .replace("{user}", ctx.author.mention)
            .replace("{user_name}", ctx.author.display_name)
            .replace("{server}", ctx.guild.name)
            .replace("{count}", str(ctx.guild.member_count))
        )
        embed = discord.Embed(
            title="✅ Welcome message saved",
            description=preview,
            color=0x57E389,
        )
        embed.set_footer(text=f"Will greet new members in #{ctx.channel.name}")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='welcome_preview', description='[Admin] Preview the current welcome message')
    @commands.has_permissions(administrator=True)
    async def welcome_preview(self, ctx):
        msg = await db.get_setting(SETTING_MSG_KEY)
        ch_id = await db.get_setting(SETTING_CH_KEY)
        if not msg:
            await ctx.send("⚠️ No welcome message set. Use `/setup_welcome message:…` in the channel you want it posted in.", ephemeral=True)
            return
        preview = (
            msg.replace("{user}", ctx.author.mention)
               .replace("{user_name}", ctx.author.display_name)
               .replace("{server}", ctx.guild.name)
               .replace("{count}", str(ctx.guild.member_count))
        )
        ch = ctx.guild.get_channel(int(ch_id)) if ch_id else None
        embed = discord.Embed(title="👋 Welcome preview", description=preview, color=0x57E389)
        embed.set_footer(text=f"Target channel: {ch.mention if ch else 'not set'}")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='welcome_clear', description='[Admin] Clear the welcome message')
    @commands.has_permissions(administrator=True)
    async def welcome_clear(self, ctx):
        await db.delete_setting(SETTING_MSG_KEY)
        await db.delete_setting(SETTING_CH_KEY)
        await ctx.send("🗑️ Welcome message cleared.")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        try:
            msg = await db.get_setting(SETTING_MSG_KEY)
            if not msg:
                return
            ch_id = await db.get_setting(SETTING_CH_KEY)
            if not ch_id:
                return
            channel = member.guild.get_channel(int(ch_id))
            if channel is None:
                return
            text = (
                msg.replace("{user}", member.mention)
                   .replace("{user_name}", member.display_name)
                   .replace("{server}", member.guild.name)
                   .replace("{count}", str(member.guild.member_count))
            )
            await channel.send(text)
        except Exception as e:
            print(f"[welcome] on_member_join error: {e}")


async def setup(bot):
    await bot.add_cog(Welcome(bot))
