import discord
from discord.ext import commands

intents = discord.Intents.all()

tokens = []
with open('config.txt') as file:
    for line in file:
        line = line.strip()
        if line:
            items = [item.strip() for item in line.split('=')]
            tokens.append(items[1])

bot_token = tokens[0]
url = tokens[1]
ffmpegPath = 'ffmpeg.exe'
client = commands.Bot(command_prefix = tokens[2], intents = intents)

@client.event
async def on_presence_update(before, after):
    if str(before.activity) != str(after.activity):
        if (after.activity is not None and str(after.activity.name) == 'Valheim'):
            if (after.voice is not None):
                voice_channel = after.voice.channel
                # Finds an available voice client for the bot.
                voice = discord.utils.get(client.voice_clients, guild=after.guild)
                if not voice:
                    await voice_channel.connect()
                    voice = discord.utils.get(client.voice_clients, guild=after.guild)
                if not voice.is_playing():
                    voice.play(discord.FFmpegOpusAudio(executable=ffmpegPath, source=url))
@client.event
async def on_voice_state_update(member, before, after):
    voice_state = member.guild.voice_client
    # Checking if the bot is connected to a channel and if there is only 1 member connected to it (the bot itself)
    if voice_state is not None and len(voice_state.channel.members) == 1:
        # You should also check if the song is still playing
        await voice_state.disconnect()

client.run(bot_token)
