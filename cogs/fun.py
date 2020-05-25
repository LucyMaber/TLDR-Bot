import discord
import re
import requests
import config
import random
import json
from io import BytesIO
from modules import command, embed_maker
from discord.ext import commands


class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(help='Gets a random cat image', usage='cat', examples=['cat'],
                      clearance='User', cls=command.Command)
    async def cat(self, ctx):
        url = 'http://aws.random.cat/meow'
        response = requests.get(url)
        json_text = response.text.encode("ascii", "ignore").decode('ascii')

        img_url = json.loads(json_text)['file']
        # get image extension
        split = img_url.split('.')
        extension = split[-1]

        image_response = requests.get(img_url)
        image = BytesIO(image_response.content)
        image.seek(0)

        embed = discord.Embed()
        embed.set_footer(text=ctx.author, icon_url=ctx.author.avatar_url)
        embed.set_image(url=f'attachment://cat.{extension}')
        return await ctx.send(file=discord.File(fp=image, filename=f'cat.{extension}'), embed=embed)

    @commands.command(help='Gets a random dad joke', usage='dadjoke', examples=['dadjoke'],
                      clearance='User', cls=command.Command)
    async def dadjoke(self, ctx):
        url = "https://icanhazdadjoke.com/"
        response = requests.get(url, headers={"Accept": "text/plain"})
        joke = response.text.encode("ascii", "ignore").decode("ascii")

        return await embed_maker.message(ctx, joke)

    @commands.command(help='Distort images or peoples profile pictures', usage='distort [image link | @Member]',
                      examples=['disort https://i.imgur.com/75Jr3.jpg', 'distort @Hattyot', 'distort Hattyot'],
                      clearance='User', cls=command.Command)
    async def distort(self, ctx, source=None):
        url = None
        mem = None

        # check for attachments
        if ctx.message.attachments:
            url = ctx.message.attachments[0].url

        # check if source is member
        if source and ctx.message.mentions:
            mem = ctx.message.mentions[0]
        elif source:
            # check if source is emote
            emote_regex = re.compile(r'<:[a-zA-Z0-9_]+:([0-9]+)>$')
            match = re.findall(emote_regex, source)
            if match:
                emote = [emote for emote in ctx.guild.emojis if str(emote.id) == match[0]][0]
                url = str(emote.url)
            else:
                # Check if source is member name or id
                regex = re.compile(fr'({source.lower()})')
                mem = discord.utils.find(lambda m: re.findall(regex, m.name.lower()) or re.findall(regex, m.display_name.lower()) or m.id == source, ctx.guild.members)
                if mem is None:
                    url = source

        if source is None:
            mem = ctx.author

        # Choose a random member
        if source == 'random':
            mem = random.choice(ctx.guild.members)

        if mem and url is None:
            url = str(mem.avatar_url).replace('webp', 'png')

        response = requests.get(f'{config.WEB_API_URL}/distort?img={url}')
        if not response:
            return await embed_maker.message(ctx, 'Error getting image', colour='red')

        distorted_image = BytesIO(response.content)
        distorted_image.seek(0)

        embed = discord.Embed()
        embed.set_footer(text=ctx.author, icon_url=ctx.author.avatar_url)
        embed.set_image(url='attachment://distorted.png')
        return await ctx.send(file=discord.File(fp=distorted_image, filename='distorted.png'), embed=embed)


def setup(bot):
    bot.add_cog(Fun(bot))
