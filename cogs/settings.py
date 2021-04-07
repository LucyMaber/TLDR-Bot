import discord
import config

from bot import TLDR
from discord.ext import commands
from modules import database, cls, embed_maker
from datetime import datetime

db = database.get_connection()


class Settings(commands.Cog):
    def __init__(self, bot: TLDR):
        self.bot = bot

    @commands.command(
        help='Change the channel where level up messages are sent',
        usage='level_up_channel [#channel]',
        examples=['level_up_channel #bots'],
        clearance='Mod',
        cls=cls.Command
    )
    async def level_up_channel(self, ctx: commands.Context, channel: discord.TextChannel = None):
        leveling_guild = self.bot.leveling_system.get_guild(ctx.guild.id)
        current_channel_id = leveling_guild.level_up_channel

        if not current_channel_id:
            current_channel_string = 'Not set, defaults to message channel'
        else:
            current_channel_string = f'<#{current_channel_id}>'

        if channel is None:
            embed_colour = config.EMBED_COLOUR
            embed = discord.Embed(colour=embed_colour, timestamp=datetime.now(), description='Change the channel where level up announcements are sent.')
            embed.add_field(name='>Current Settings', value=current_channel_string, inline=False)
            embed.add_field(name='>Update', value='`level_up_channel [#channel]`', inline=False)
            embed.add_field(name='>Valid Input', value='**Channel:** Any text channel | mention only', inline=False)
            embed.set_footer(text=ctx.author, icon_url=ctx.author.avatar_url)
            embed.set_author(name='Level Up Channel', icon_url=ctx.guild.icon_url)
            return await ctx.send(embed=embed)

        if channel:
            if channel.id == current_channel_id:
                return await embed_maker.error(ctx, f'Level up channel is already set to <#{channel.id}>')

            leveling_guild.level_up_channel = channel.id
            return await embed_maker.message(
                ctx,
                description=f'Level up channel has been set to <#{channel.id}>',
                colour='green',
                send=True
            )
        else:
            return await embed_maker.command_error(ctx, '[#channel]')


def setup(bot):
    bot.add_cog(Settings(bot))
