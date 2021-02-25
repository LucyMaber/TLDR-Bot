import discord
import dateparser
import datetime
import time
import config
import re

from cogs import utility
from bson import ObjectId
from typing import Union
from discord.ext import commands
from bot import TLDR
from modules import cls, database, embed_maker
from modules.utils import (
    ParseArgs,
    Command,
    get_custom_emote,
    get_guild_role,
    get_member
)
db = database.Connection()


class Mod(commands.Cog):
    def __init__(self, bot: TLDR):
        self.bot = bot

    @commands.group(
        name='watchlist',
        help='Manage the watchlist, which logs all the users message to a channel',
        usage='watchlist (sub command) (args)',
        examples=['watchlist'],
        sub_commands=['add', 'remove', 'add_filters'],
        clearance='Mod',
        cls=cls.Group
    )
    async def watchlist(self, ctx: commands.Context):
        if ctx.subcommand_passed is None:
            users_on_list = [d for d in db.watchlist.distinct('user_id', {'guild_id': ctx.guild.id})]

            list_embed = await embed_maker.message(
                ctx,
                author={'name': 'Users on the watchlist'}
            )

            on_list_str = ''
            for i, user_id in enumerate(users_on_list):
                user = ctx.guild.get_member(int(user_id))
                if user is None:
                    try:
                        user = await ctx.guild.fetch_member(int(user_id))
                    except:
                        # remove user from the watchlist if user isnt on the server anymore
                        db.watchlist.delete_one({'guild_id': ctx.guild.id, 'user_id': user_id})
                        continue

                on_list_str += f'`#{i + 1}` - {str(user)}\n'
                watchlist_user = db.watchlist.find_one({'guild_id': ctx.guild.id, 'user_id': user_id}, {'filters': 1})
                if watchlist_user['filters']:
                    on_list_str += 'Filters: ' + " | ".join(f"`{f}`" for f in watchlist_user['filters'])
                on_list_str += '\n\n'

            list_embed.description = 'Currently no users are on the watchlist' if not on_list_str else on_list_str

            return await ctx.send(embed=list_embed)

    @watchlist.command(
        name='add',
        help='add a user to the watchlist, with optionl filters (mathces are found with regex)',
        usage='watchlist add [user] -f (filter1) -f (filter2)...',
        examples=[r'watchlist add hattyot -f hattyot -f \sot\s -f \ssus\s'],
        clearance='Mod',
        parse_args=['f'],
        cls=cls.Command
    )
    async def watchlist_add(self, ctx: commands.Context, *, args: Union[ParseArgs, dict] = None):
        if not args:
            return await embed_maker.command_error(ctx)

        if 'pre' not in args or not args['pre']:
            return await embed_maker.error(ctx, 'Missing user')

        user_identifier = args['pre']
        filters = args['f'] if 'f' in args else []

        member = await get_member(ctx, user_identifier)
        if type(member) == discord.Message:
            return

        watchlist_user = db.watchlist.find_one({'guild_id': ctx.guild.id, 'user_id': member.id})
        if watchlist_user:
            return await embed_maker.error(ctx, 'User is already on the watchlist')

        watchlist_category = discord.utils.find(lambda c: c.name == 'Watchlist', ctx.guild.categories)
        if watchlist_category is None:
            # get all staff roles
            staff_roles = filter(lambda r: r.permissions.manage_messages, ctx.guild.roles)

            # staff roles can read channels in category, users cant
            overwrites = dict.fromkeys(staff_roles, discord.PermissionOverwrite(read_messages=True, send_messages=True,
                                                                                read_message_history=True))
            overwrites[ctx.guild.default_role] = discord.PermissionOverwrite(read_messages=False)

            watchlist_category = await ctx.guild.create_category(name='Watchlist', overwrites=overwrites)

        watchlist_channel = await ctx.guild.create_text_channel(f'{member.name}', category=watchlist_category)

        watchlist_doc = {
            'guild_id': ctx.guild.id,
            'user_id': member.id,
            'filters': filters,
            'channel_id': watchlist_channel.id
        }
        db.watchlist.insert_one(watchlist_doc)

        msg = f'<@{member.id}> has been added to the watchlist'
        if filters:
            msg += f'\nWith these filters: {" or ".join(f"`{f}`" for f in filters)}'

        return await embed_maker.message(ctx, description=msg, colour='green', send=True)

    @watchlist.command(
        name='remove',
        help='remove a user from the watchlist',
        usage='watchlist remove [user]',
        examples=['watchlist remove hattyot'],
        clearance='Mod',
        cls=cls.Command
    )
    async def watchlist_remove(self, ctx: commands.Context, *, user: str = None):
        if user is None:
            return await embed_maker.command_error(ctx)

        member = await get_member(ctx, user)
        if type(member) == discord.Message:
            return

        watchlist_user = db.watchlist.find_one({'guild_id': ctx.guild.id, 'user_id': member.id})

        if watchlist_user is None:
            return await embed_maker.error(ctx, 'User is not on the list')

        # remove watchlist channel
        channel_id = watchlist_user['channel_id']
        channel = self.bot.get_channel(int(channel_id))
        if channel:
            await channel.delete()

        db.watchlist.delete_one({'guild_id': ctx.guild.id, 'user_id': member.id})

        return await embed_maker.message(
            ctx,
            description=f'<@{member.id}> has been removed from the watchlist',
            colour='green',
            send=True
        )

    @watchlist.command(
        name='add_filters',
        help='Add filters to a user on the watchlist, when a user message matches the filter, mods are pinged.',
        usage='watchlist add_filters [user] -f (filter 1 | filter 2)',
        examples=[r'watchlist add_filters hattyot -f filter 1 -f \sfilter 2\s'],
        parse_args=['f'],
        clearance='Mod',
        cls=cls.Command
    )
    async def watchlist_add_filters(self, ctx: commands.Context, *, args: Union[ParseArgs, dict] = None):
        if not args:
            return await embed_maker.command_error(ctx)

        if 'f' not in args or not args['f']:
            return await embed_maker.error(ctx, 'Missing filters')

        if 'pre' not in args or not args['pre']:
            return await embed_maker.error(ctx, 'Missing user')

        user_identifier = args['pre']
        filters = args['f']

        member = await get_member(ctx, user_identifier)
        if type(member) == discord.Embed:
            return await embed_maker.error(ctx, 'Invalid member')

        watchlist_user = db.watchlist.find_one({'guild_id': ctx.guild.id, 'user_id': member.id})
        if watchlist_user is None:
            return await embed_maker.error(ctx, 'User is not on the list')

        all_filters = watchlist_user['filters']
        if all_filters:
            filters += all_filters

        db.watchlist.update_one({'guild_id': ctx.guild.id, 'user_id': member.id}, {'$set': {f'filters': filters}})

        return await embed_maker.message(
            ctx,
            description=f'if {member} mentions {" or ".join(f"`{f}`" for f in filters)} mods will be @\'d',
            colour='green',
            send=True
        )

    @commands.group(
        help='Daily debate scheduler/manager',
        usage='dailydebates (sub command) (arg(s))',
        clearance='Mod',
        aliases=['dd', 'dailydebate'],
        examples=['dailydebates'],
        sub_commands=['add', 'insert', 'remove', 'set_time', 'set_channel', 'set_role', 'set_poll_channel',
                      'set_poll_options', 'disable'],
        cls=cls.Group,

    )
    async def dailydebates(self, ctx: commands.Context):
        daily_debates_data = db.get_daily_debates(ctx.guild.id)
        if ctx.subcommand_passed is None:
            # List currently set up daily debate topics
            topics = daily_debates_data['topics']
            if not topics:
                topics_str = f'Currently there are no debate topics set up'
            else:
                # generate topics string
                topics_str = '**Topics:**\n'
                for i, topic in enumerate(topics):
                    topic_str = topic['topic']
                    topic_author_id = topic['topic_author_id']
                    topic_options = topic['topic_options']
                    topic_author = await ctx.guild.fetch_member(int(topic_author_id)) if topic_author_id else None

                    topics_str += f'`#{i + 1}`: {topic_str}\n'
                    if topic_author:
                        topics_str += f'**Topic Author:** {str(topic_author)}\n'

                    if topic_options:
                        topics_str += '**Poll Options:**' + ' |'.join([f' `{o}`' for i, o in enumerate(topic_options.values())]) + '\n'

            dd_time = daily_debates_data['time'] if daily_debates_data['time'] else 'Not set'
            dd_channel = f'<#{daily_debates_data["channel_id"]}>' if daily_debates_data['channel_id'] else 'Not set'
            dd_poll_channel = f'<#{daily_debates_data["poll_channel_id"]}>' if daily_debates_data['poll_channel_id'] else 'Not set'
            dd_role = f'<@&{daily_debates_data["role_id"]}>' if daily_debates_data['role_id'] else 'Not set'

            embed = await embed_maker.message(
                ctx,
                description=topics_str,
                author={'name': 'Daily Debates'}
            )
            embed.add_field(
                name='Attributes',
                value=f'**Time:** {dd_time}\n**Channel:** {dd_channel}\n**Poll Channel:** {dd_poll_channel}\n**Role:** {dd_role}'
            )

            return await ctx.send(embed=embed)

    @dailydebates.command(
        name='disable',
        help='Disable the daily debates system, time will be set to 0',
        usage='dailydebates disable',
        examples=['dailydebates disable'],
        clearance='Mod',
        cls=cls.Command
    )
    async def dailydebates_disable(self, ctx: commands.Context):
        db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {'time': 0}})

        # cancel timer if active
        daily_debate_timer = db.timers.find_one(
            {'guild_id': ctx.guild.id, 'event': {'$in': ['daily_debate', 'daily_debate_final']}}
        )
        if daily_debate_timer:
            db.timers.delete_one({'_id': ObjectId(daily_debate_timer['_id'])})

        return await embed_maker.message(ctx, description='Daily debates have been disabled', send=True)

    @dailydebates.command(
        name='set_poll_options',
        help='Set the poll options for a daily debate topic',
        usage='dailydebates set_poll_options [index of topic] -o [option 1] -o [option 2] -o (emote: option 3)...',
        examples=[
            'dailydebates set_poll_options 1 -o yes -o no -o double yes -o double no',
            'dailydebates set_poll_options 1 -o 🇩🇪: Germany -o 🇬🇧: UK'
        ],
        clearance='Mod',
        cls=cls.Command
    )
    async def dailydebates_set_poll_options(self, ctx: commands.Context, index: str = None, *, args: Union[ParseArgs, dict] = None):
        if index is None:
            return await embed_maker.command_error(ctx)

        if not index.isdigit():
            return await embed_maker.command_error(ctx, '[index of topic]')

        if 'o' not in args or not args['o']:
            return await embed_maker.error(ctx, 'Missing options')

        emote_options = await utility.Utility.parse_poll_options(ctx, args['o'])
        if type(emote_options) == discord.Message:
            return

        daily_debates_data = db.daily_debates.find_one({'guild_id': ctx.guild.id})
        topics = daily_debates_data['topics']

        index = int(index)
        if len(topics) < index:
            return await embed_maker.error(ctx, 'index out of range')

        topic = topics[index - 1]

        topic_obj = {
            'topic': topic['topic'],
            'topic_author_id': topic['topic_author_id'],
            'topic_options': emote_options
        }

        db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {f'topics.{index - 1}': topic_obj}})
        options_str = '\n'.join([f'{emote}: {option}' for emote, option in emote_options.items()])
        return await embed_maker.message(
            ctx,
            description=f'Along with the topic: **"{topic["topic"]}"**\nwill be sent a poll with these options: {options_str}',
            send=True
        )

    @dailydebates.command(
        name='add',
        help='add a topic to the list topics along with optional options and topic author',
        usage='dailydebates add [topic] -ta (topic author) -o (option1) -o (option2)',
        examples=[
            'dailydebates add is ross mega cool? -ta hattyot -o yes -o double yes -o triple yes'
        ],
        parse_args=['ta', 'o'],
        clearance='Mod',
        cls=cls.Command
    )
    async def dailydebates_add(self, ctx: commands.Context, *, args: Union[ParseArgs, dict] = None):
        if args is None:
            return await embed_maker.command_error(ctx)

        args = await self.parse_dd_args(ctx, args)
        if type(args) == discord.Message:
            return

        topic = args['pre']
        topic_author = args['ta']
        topic_options = args['o']

        topic_obj = {
            'topic': topic,
            'topic_author_id': topic_author,
            'topic_options': topic_options
        }
        db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$push': {'topics': topic_obj}})

        daily_debate_data = db.daily_debates.find_one({'guild_id': ctx.guild.id})
        await embed_maker.message(
            ctx,
            description=f'`{topic}` has been added to the list of daily debate topics'
                        f'\nThere are now **{len(daily_debate_data["topics"])}** topics on the list',
            send=True
        )

        daily_debate_timer = db.timers.find_one(
            {'guild_id': ctx.guild.id, 'event': {'$in': ['daily_debate', 'daily_debate_final']}}
        )
        if not daily_debate_timer:
            return await self.start_daily_debate_timer(ctx.guild.id, daily_debate_data['time'])

    @dailydebates.command(
        name='insert',
        help='insert a topic into the first place on the list of topics along with optional options and topic author',
        usage='dailydebates insert [topic] -ta (topic author) -o (poll options)',
        examples=['dailydebates insert is ross mega cool? -ta hattyot -o yes | double yes | triple yes'],
        clearance='Mod',
        parse_args=['ta', 'o'],
        cls=cls.Command
    )
    async def _dailydebates_insert(self, ctx: commands.Context, *, args: Union[ParseArgs, dict] = None):
        if args is None:
            return await embed_maker.command_error(ctx)

        args = await self.parse_dd_args(ctx, args)
        if type(args) == discord.Message:
            return

        topic = args['pre']
        topic_author = args['ta']
        topic_options = args['o']

        topic_obj = {
            'topic': topic,
            'topic_author_id': topic_author,
            'topic_options': topic_options
        }
        db.daily_debates.update_one(
            {'guild_id': ctx.guild.id},
            {'$push': {'topics': {'$each': [topic_obj], '$position': 0}}}
        )

        daily_debate_data = db.daily_debates.find_one({'guild_id': ctx.guild.id})
        await embed_maker.message(
            ctx,
            description='`{topic}` has been inserted into first place in the list of daily debate topics'
                        f'\nThere are now **{len(daily_debate_data["topics"])}** topics on the list',
            send=True
        )

        daily_debate_timer = db.timers.find_one(
            {'guild_id': ctx.guild.id, 'event': {'$in': ['daily_debate', 'daily_debate_final']}}
        )
        if not daily_debate_timer:
            return await self.start_daily_debate_timer(ctx.guild.id, daily_debate_data['time'])

    @dailydebates.command(
        name='remove',
        help='remove a topic from the topic list',
        usage='dailydebates remove [topic index]',
        examples=['dailydebates remove 2'],
        clearance='Mod',
        cls=cls.Command
    )
    async def dailydebates_remove(self, ctx: commands.Context, index: str = None):
        if index is None:
            return await embed_maker.command_error(ctx)

        if not index.isdigit():
            return await embed_maker.error(ctx, 'Invalid index')

        daily_debate_data = db.daily_debates.find_one({'guild_id': ctx.guild.id})

        index = int(index)
        if index > len(daily_debate_data['topics']):
            return await embed_maker.error(ctx, 'Index too big')

        if index < 1:
            return await embed_maker.error(ctx, 'Index cant be smaller than 1')

        topic_to_delete = daily_debate_data['topics'][index - 1]
        db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$pull': {'topics': topic_to_delete}})

        return await embed_maker.message(
            ctx,
            description='`{topic_to_delete["topic"]}` has been removed from the list of daily debate topics'
                        f'\nThere are now **{len(daily_debate_data["topics"]) - 1}** topics on the list',
            send=True
        )

    @dailydebates.command(
        name='set_time',
        help='set the time when topics are announced',
        usage='dailydebates set_time [time]',
        examples=['dailydebates set_time 14:00 GMT+1'],
        clearance='Mod',
        cls=cls.Command
    )
    async def dailydebates_set_time(self, ctx: commands.Context, *, time_str: str = None):
        if time_str is None:
            return await embed_maker.command_error(ctx)

        parsed_time = dateparser.parse(time_str, settings={'RETURN_AS_TIMEZONE_AWARE': True})
        if not parsed_time:
            return await embed_maker.error(ctx, 'Invalid time')

        parsed_dd_time = dateparser.parse(
            time_str,
            settings={
                'PREFER_DATES_FROM': 'future',
                'RETURN_AS_TIMEZONE_AWARE': True,
                'RELATIVE_BASE': datetime.datetime.now(parsed_time.tzinfo)
            }
        )
        time_diff = parsed_dd_time - datetime.datetime.now(parsed_dd_time.tzinfo)
        time_diff_seconds = round(time_diff.total_seconds())

        if time_diff_seconds < 0:
            return await embed_maker.error(ctx, 'Invalid time')

        db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {'time': time_str}})
        await embed_maker.message(ctx, description=f'Daily debates will now be announced every day at {time_str}', send=True)

        # cancel old timer
        db.timers.delete_many({'guild_id': ctx.guild.id, 'event': {'$in': ['daily_debate', 'daily_debate_final']}})

        return await self.start_daily_debate_timer(ctx.guild.id, time_str)

    @dailydebates.command(
        name='set_channel',
        help=f'set the channel where topics are announced',
        usage='dailydebates set_channel [#set_channel]',
        examples=['dailydebates set_channel #daily-debates'],
        clearance='Mod',
        cls=cls.Command
    )
    async def dailydebates_set_channel(self, ctx: commands.Context, channel: discord.TextChannel = None):
        if channel is None:
            return await embed_maker.command_error(ctx)

        db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {'channel_id': channel.id}})
        return await embed_maker.message(
            ctx,
            description=f'Daily debates will now be announced every day at <#{channel.id}>',
            send=True
        )

    @dailydebates.command(
        name='set_role',
        help=f'set the role that will be @\'d when topics are announced, disable @\'s by setting the role to `None`',
        usage='dailydebates set_role [role]',
        examples=['dailydebates set_role Debater'],
        clearance='Mod',
        cls=cls.Command
    )
    async def dailydebates_set_role(self, ctx: commands.Context, *, role: Union[discord.Role, str] = None):
        if role is None:
            return await embed_maker.command_error(ctx)

        if type(role) == str and role.lower() == 'none':
            db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {'role_id': 0}})
            return await embed_maker.message(ctx, description='daily debates role has been disabled', send=True)
        elif type(role) == str:
            return await embed_maker.command_error(ctx, '[role]')

        db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {'role_id': role.id}})
        return await embed_maker.message(
            ctx,
            description=f'Daily debates will now be announced every day to <@&{role.id}>',
            send=True
        )

    @dailydebates.command(
        name='set_poll_channel',
        help=f'Set the poll channel where polls will be sent, disable polls by setting poll channel to `None``',
        usage='dailydebates set_poll_channel [#channel]',
        examples=['dailydebates set_poll_channel #daily_debate_polls'],
        clearance='Mod',
        cls=cls.Command
    )
    async def dailydebates_set_poll_channel(self, ctx: commands.Context, channel: Union[discord.TextChannel, str] = None):
        if channel is None:
            return await embed_maker.command_error(ctx)

        if type(channel) == str and channel.lower() == 'none':
            db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {'role_id': 0}})
            return await embed_maker.message(ctx, description='daily debates poll channel has been disabled', send=True)

        db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {'poll_channel_id': channel.id}})
        return await embed_maker.message(
            ctx,
            description=f'Daily debate polls will now be sent every day to <#{channel.id}>',
            send=True
        )

    @staticmethod
    async def parse_dd_args(ctx: commands.Context, args: dict):
        if 'pre' not in args or not args['pre']:
            return await embed_maker.error(ctx, 'Missing topic')

        args['ta'] = args['ta'][0] if 'ta' in args else ''
        args['o'] = await utility.Utility.parse_poll_options(ctx, args['o']) if 'o' in args else ''

        if type(args['o']) == discord.Message:
            return

        if args['ta']:
            member = await get_member(ctx, args['ta'])
            if type(member) == discord.Message:
                return member

            args['ta'] = member.id

        return args

    async def start_daily_debate_timer(self, guild_id, dd_time):
        # delete old timer
        db.timers.delete_many({'guild_id': guild_id, 'event': {'$in': ['daily_debate', 'daily_debate_final']}})

        # creating first parsed_dd_time to grab timezone info
        parsed_dd_time = dateparser.parse(dd_time, settings={'RETURN_AS_TIMEZONE_AWARE': True})

        # second one for actual use
        parsed_dd_time = dateparser.parse(dd_time, settings={'PREFER_DATES_FROM': 'future', 'RETURN_AS_TIMEZONE_AWARE': True, 'RELATIVE_BASE': datetime.datetime.now(parsed_dd_time.tzinfo)})

        time_diff = parsed_dd_time - datetime.datetime.now(parsed_dd_time.tzinfo)
        time_diff_seconds = round(time_diff.total_seconds())

        # -1h so mods can be warned when there are no daily debate topics set up
        timer_expires = round(time.time()) + time_diff_seconds - 3600  # one hour
        self.bot.timers.create(guild_id=guild_id, expires=timer_expires, event='daily_debate', extras={})

    @commands.group(
        invoke_without_command=True,
        help='Grant users access to commands that aren\'t available to users or take away their access to a command',
        usage='command_access [<member/role>/sub command] (args)',
        clearance='Admin',
        examples=[
            'command_access Hatty',
            'command_access Mayor'
        ],
        sub_commands=['give', 'take', 'default'],
        cls=cls.Group
    )
    async def command_access(self, ctx: commands.Context, user_input: Union[discord.Role, str] = None):
        if user_input is None:
            return await embed_maker.command_error(ctx)

        if ctx.subcommand_passed is None:
            return

        if type(user_input) == str:
            # check if user input is member
            user_input = await get_member(ctx, user_input)
            if type(user_input) == discord.Message:
                return

        if type(user_input) == discord.Role:
            access_type = 'role'
        elif type(user_input) == discord.Member:
            access_type = 'user'

        special_access = [c for c in db.commands.find(
            {'guild_id': ctx.guild.id, f'{access_type}_access.{user_input.id}': {'$exists': True}}
        )]

        access_given = [a['command_name'] for a in special_access if a[f'{access_type}_access'][f'{user_input.id}'] == 'give']
        access_taken = [a['command_name'] for a in special_access if a[f'{access_type}_access'][f'{user_input.id}'] == 'take']

        access_given_str = ' |'.join([f' `{c}`' for c in access_given])
        access_taken_str = ' |'.join([f' `{c}`' for c in access_taken])

        if not access_given_str:
            access_given_str = f'{access_type.title()} has no special access to commands'
        if not access_taken_str:
            access_taken_str = f'No commands have been taken away from this {access_type.title()}'

        embed = await embed_maker.message(
            ctx,
            author={'name': f'Command Access - {user_input}'}
        )

        embed.add_field(name='>Access Given', value=access_given_str, inline=False)
        embed.add_field(name='>Access Taken', value=access_taken_str, inline=False)

        return await ctx.send(embed=embed)

    async def command_access_check(self, ctx: commands.Context, command: cls.Command,
                                   user_input: Union[discord.Role, str],
                                   change: str):

        if type(user_input) == str:
            # check if user input is member
            user_input = await get_member(ctx, user_input)
            if type(user_input) == discord.Message:
                return

        if command is None:
            return await embed_maker.command_error(ctx)

        if user_input is None:
            return await embed_maker.error(ctx, '[user/role]')

        command_data = db.get_command_data(ctx.guild.id, command.name, insert=True)

        if command.clearance in ['Dev', 'Admin']:
            return await embed_maker.error(ctx, 'You can not manage access of admin or dev commands')

        can_access_command = True

        if type(user_input) == discord.Role:
            access_type = 'role'
        elif type(user_input) == discord.Member:
            access_type = 'user'

        if access_type == 'user':
            author_perms = ctx.author.guild_permissions
            member_perms = user_input.guild_permissions
            if author_perms <= member_perms:
                return await embed_maker.error(
                    ctx,
                    'You can not manage command access of people who have the same or more permissions as you'
                )

            # can user run command
            can_access_command = self.bot.can_run_command(command, user_input)

        elif access_type == 'role':
            top_author_role = ctx.author.roles[-1]
            top_author_role_perms = top_author_role.permissions
            role_perms = user_input.permissions
            if top_author_role_perms <= role_perms:
                return await embed_maker.error(
                    ctx,
                    'You can not manage command access of a role which has the same or more permissions as you'
                )

            access = command_data[f'role_access']
            can_access_command = str(user_input.id) in access and access[str(user_input.id)] == 'give'

        if can_access_command and change == 'give':
            return await embed_maker.error(ctx, f'{user_input} already has access to that command')

        if not can_access_command and change == 'take':
            return await embed_maker.error(ctx, f"{user_input} already doesn't have access to that command")

        return access_type, user_input

    @command_access.command(
        name='give',
        help='Grant a users or a role access to commands that aren\'t available them usually',
        usage='command_access give [command] [user/role]',
        clearance='Admin',
        examples=[
            'command_access give anon_poll Hattyot',
            'command_access give daily_debates Mayor'
        ],
        cls=cls.Command
    )
    async def command_access_give(self, ctx: commands.Context, command: Union[Command, cls.Command] = None,
                                  user_input: Union[discord.Role, str] = None):
        access_type, user_input = await self.command_access_check(ctx, command, user_input, change='give')
        if type(access_type) == discord.Message:
            return

        db.commands.update_one(
            {'guild_id': ctx.guild.id, 'command_name': command.name},
            {'$set': {f'{access_type}_access.{user_input.id}': 'give'}}
        )

        return await embed_maker.message(
            ctx,
            description=f'{user_input} has been granted access to: `{command.name}`',
            send=True
        )

    @command_access.command(
        name='take',
        help="'Take away user's or role's access to a command",
        usage='command_access take [command] [user/role]',
        clearance='Admin',
        examples=[
            'command_access take anon_poll Hattyot',
            'command_access take daily_debates Mayor'
        ],
        cls=cls.Command
    )
    async def command_access_take(self, ctx: commands.Context, command: Union[Command, cls.Command] = None,
                                  user_input: Union[discord.Role, str] = None):
        access_type, user_input = await self.command_access_check(ctx, command, user_input, change='take')
        if type(access_type) == discord.Message:
            return

        db.commands.update_one(
            {'guild_id': ctx.guild.id, 'command_name': command.name},
            {'$set': {f'{access_type}_access.{user_input.id}': 'take'}}
        )

        return await embed_maker.message(
            ctx,
            description=f'{user_input} access has been taken away from: `{command.name}`',
            send=True
        )

    @command_access.command(
        name='default',
        help="Sets role's or user's access to a command back to default",
        usage='command_access default [command] [user/role]',
        clearance='Admin',
        examples=[
            'command_access default anon_poll Hattyot',
            'command_access default daily_debates Mayor'
        ],
        cls=cls.Command
    )
    async def command_access_default(self, ctx: commands.Context, command: Union[Command, cls.Command] = None,
                                     user_input: Union[discord.Role, str] = None):
        access_type, user_input = await self.command_access_check(ctx, command, user_input, change='default')
        if type(access_type) == discord.Message:
            return

        db.commands.update_one(
            {'guild_id': ctx.guild.id, 'command_name': command.name},
            {'$unset': {f'{access_type}_access.{user_input.id}': 1}}
        )

        return await embed_maker.message(
            ctx,
            description=f'{user_input} access has been set to default for: `{command.name}`',
            send=True
        )

    @commands.command(
        help='see what roles are whitelisted for an emote or what emotes are whitelisted for a role',
        usage='emote_roles [emote/role]',
        examples=[
            'emote_roles :TldrNewsUK:',
            'emote_roles Mayor'
        ],
        clearance='Mod',
        cls=cls.Command
    )
    async def emote_roles(self, ctx, user_input: str = None):
        if user_input is None:
            return await embed_maker.command_error(ctx)

        # check if user_input is emote
        role = None

        emote = get_custom_emote(ctx, user_input)
        if not emote:
            role = await get_guild_role(ctx.guild, user_input)

        if emote:
            if emote.roles:
                return await embed_maker.message(
                    ctx,
                    description=f'This emote is restricted to: {", ".join([f"<@&{r.id}>" for r in emote.roles])}',
                    send=True
                )
            else:
                return await embed_maker.message(ctx, description='This emote is available to everyone', send=True)
        elif role:
            emotes = []
            for emote in ctx.guild.emojis:
                if role in emote.roles:
                    emotes.append(emote)

            if emotes:
                return await embed_maker.message(
                    ctx,
                    description=f'This role has access to: {", ".join([f"<:{emote.name}:{emote.name}> " for emote in emotes])}',
                    send=True
                )
            else:
                return await embed_maker.message(
                    ctx,
                    description='This role doesn\'t have special access to any emotes',
                    send=True
                )

    @commands.command(
        help='restrict an emote to specific role(s)',
        usage='emote_role (action) -r [role] -e [emote 1] (emote 2)...',
        examples=[
            'emote_role',
            'emote_role add -r Mayor -e :TldrNewsUK:',
            'emote_role remove -r Mayor -e :TldrNewsUK: :TldrNewsUS: :TldrNewsEU:'
        ],
        clearance='Mod',
        cls=cls.Command
    )
    async def emote_role(self, ctx: commands.Context, action: str = None, *, args: Union[ParseArgs, dict] = None):
        if action.isdigit():
            page = int(action)
        else:
            page = 1
        if action is None:
            emotes = ctx.guild.emojis
            description = ''
            for emote in emotes:
                emote_roles = " | ".join(f'<@&{role.id}>' for role in emote.roles)
                if not emote_roles:
                    continue

                description += f'\n{emote} -> {emote_roles}'

            return await embed_maker.message(
                ctx,
                description=description,
                send=True
            )

            return await embed_maker.command_error(ctx)

        if action not in ['add', 'remove']:
            return await embed_maker.command_error(ctx, '[action]')

        # return error if required variables are not given
        if 'r' not in args or not args['r']:
            return await embed_maker.error(ctx, "Missing role arg")

        if 'e' not in args or not args['e']:
            return await embed_maker.error(ctx, "Missing emotes arg")

        role = await get_guild_role(ctx.guild, args['r'][0])
        emotes = args['e'][0]

        if emotes is None:
            return await embed_maker.command_error(ctx, '[emotes]')

        if role is None:
            return await embed_maker.command_error(ctx, '[role]')

        emote_list = [*filter(lambda e: e is not None, [get_custom_emote(ctx, emote) for emote in emotes.split(' ')])]
        if not emote_list:
            return await embed_maker.command_error(ctx, '[emotes]')

        msg = None
        for emote in emote_list:
            emote_roles = emote.roles

            if action == 'add':
                emote_roles.append(role)
                # add bot role to emote_roles
                if ctx.guild.self_role not in emote_roles:
                    emote_roles.append(ctx.guild.self_role)

                emote_roles = [*set(emote_roles)]

                await emote.edit(roles=emote_roles)

            elif action == 'remove':
                for i, r in enumerate(emote_roles):
                    if r.id == role.id:
                        emote_roles.pop(i)
                        await emote.edit(roles=emote_roles)
                else:
                    msg = f'<@&{role.id}> is not whitelisted for emote {emote}'
                    break

        if not msg:
            if action == 'add':
                msg = f'<@&{role.id}> has been added to whitelisted roles of emotes {emotes}'
            elif action == 'remove':
                msg = f'<@&{role.id}> has been removed from whitelisted roles of emotes {emotes}'

        return await embed_maker.message(ctx, description=msg, colour='green', send=True)

    @commands.command(
        help='Open a ticket for discussion',
        usage='open_ticket [ticket]',
        clearance='Mod',
        examples=['open_ticket new mods'],
        cls=cls.Command
    )
    async def open_ticket(self, ctx: commands.Context, *, ticket=None):
        if ticket is None:
            return await embed_maker.command_error(ctx)

        main_guild = self.bot.get_guild(config.MAIN_SERVER)
        embed_colour = config.EMBED_COLOUR
        ticket_embed = discord.Embed(colour=embed_colour, timestamp=datetime.datetime.now())
        ticket_embed.set_footer(text=ctx.author, icon_url=ctx.author.avatar_url)
        ticket_embed.set_author(name='New Ticket', icon_url=main_guild.icon_url)
        ticket_embed.add_field(name='>Opened By', value=f'<@{ctx.author.id}>', inline=False)
        ticket_embed.add_field(name='>Ticket', value=ticket, inline=False)

        ticket_category = discord.utils.find(lambda c: c.name == 'Open Tickets', ctx.guild.categories)

        if ticket_category is None:
            # get all staff roles
            staff_roles = filter(lambda r: r.permissions.manage_messages, ctx.guild.roles)

            # staff roles can read channels in category, users cant
            overwrites = dict.fromkeys(staff_roles, discord.PermissionOverwrite(read_messages=True, send_messages=True, read_message_history=True))
            overwrites[ctx.guild.default_role] = discord.PermissionOverwrite(read_messages=False)

            ticket_category = await ctx.guild.create_category(name='Open Tickets', overwrites=overwrites)

        today = datetime.date.today()
        date_str = today.strftime('%Y-%m-%d')
        ticket_channel = await ctx.guild.create_text_channel(f'{date_str}-{ctx.author.name}', category=ticket_category)
        await ticket_channel.send(embed=ticket_embed)


def setup(bot):
    bot.add_cog(Mod(bot))
