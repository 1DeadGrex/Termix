import discord
from discord.ext import commands
import aiosqlite

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name='banlist', description='View recent ban history')
    @commands.has_permissions(view_audit_log=True)
    async def banlist(self, ctx):
        embed = discord.Embed(title="🔨 Ban History", color=0xff0000)
        count = 0
        async for entry in ctx.guild.audit_logs(limit=20, action=discord.AuditLogAction.ban):
            embed.add_field(
                name=f"{entry.target}",
                value=f"Banned by: {entry.user}\nReason: {entry.reason or 'No reason'}",
                inline=False
            )
            count += 1
        if count == 0:
            embed.description = "No bans recorded."
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='ban_player', description='Ban a player and log it')
    @commands.has_permissions(ban_members=True)
    async def ban_player(self, ctx, member: discord.Member, *, reason: str = "No reason"):
        await member.ban(reason=reason)
        async with aiosqlite.connect('tournament.db') as db:
            await db.execute(
                'INSERT OR REPLACE INTO bans (user_id, reason, banned_by) VALUES (?, ?, ?)',
                (member.id, reason, ctx.author.id)
            )
            await db.commit()
        await ctx.send(f"🔨 {member.mention} banned. Reason: {reason}")
    

    
    @commands.hybrid_command(name='unban', description='Unban a user by ID')
    @commands.has_permissions(ban_members=True)
    async def unban(self, ctx, user_id: int, *, reason: str = "No reason provided"):
        try:
            user = await self.bot.fetch_user(user_id)
            await ctx.guild.unban(user, reason=reason)
        except discord.NotFound:
            await ctx.send("❌ That user isn't banned or doesn't exist.")
            return
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to unban members.")
            return
        except Exception as e:
            await ctx.send(f"❌ Error: `{e}`")
            return

    # Remove from the local ban table too
        async with aiosqlite.connect('tournament.db') as db:
            await db.execute('DELETE FROM bans WHERE user_id = ?', (user_id,))
        await db.commit()

        await ctx.send(f"✅ Unbanned **{user}** (`{user_id}`). Reason: {reason}")\
        
        
async def setup(bot):
    await bot.add_cog(Moderation(bot))