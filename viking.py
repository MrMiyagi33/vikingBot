import asyncio
import os
import platform
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
prefix = tokens[2]

ffmpeg_path = 'ffmpeg.exe' if platform.system() == 'Windows' else 'ffmpeg'

client = commands.Bot(command_prefix=prefix, intents=intents)
voice_lock = asyncio.Lock()

async def play_audio_in_channel(guild, voice_channel):
    async with voice_lock:
        voice = guild.voice_client

        if voice is None or not voice.is_connected():
            try:
                voice = await voice_channel.connect(timeout=15.0, reconnect=True, self_deaf=True)
            except Exception as e:
                print(f"Failed to connect to voice channel: {e}")
                return False
        elif voice.channel != voice_channel:
            await voice.move_to(voice_channel)

        if voice and not voice.is_playing():
            try:
                source = discord.FFmpegPCMAudio(url, executable=ffmpeg_path)
                audio = discord.PCMVolumeTransformer(source)
                voice.play(audio)
                return True
            except Exception as e:
                print(f"Error playing audio stream: {e}")
                return False
        return True

@client.event
async def on_ready():
    print(f"Logged in as {client.user.name}")

# REQUIRED: Ensures prefix commands like >play get processed
@client.event
async def on_message(message):
    if message.author.bot:
        return
    await client.process_commands(message)

@client.command(name='play')
async def play_command(ctx):
    if ctx.author.voice is None or ctx.author.voice.channel is None:
        await ctx.send("You need to be in a voice channel to use this command!")
        return

    voice_channel = ctx.author.voice.channel
    success = await play_audio_in_channel(ctx.guild, voice_channel)
    
    if success:
        await ctx.send(f"Playing audio in **{voice_channel.name}**!")
    else:
        await ctx.send("Failed to join or play audio.")

@client.command(name='stop')
async def stop_command(ctx):
    voice = ctx.guild.voice_client
    if voice and voice.is_connected():
        if voice.is_playing():
            voice.stop()
        await voice.disconnect()
        await ctx.send("Disconnected from voice channel.")
    else:
        await ctx.send("I am not connected to a voice channel.")

@client.event
async def on_presence_update(before, after):
    if str(before.activity) == str(after.activity):
        return
    
    if (
        after.activity is not None 
        and str(after.activity.name) == 'Valheim' 
        and after.voice is not None 
        and after.voice.channel is not None
    ):
        await play_audio_in_channel(after.guild, after.voice.channel)

@client.event
async def on_voice_state_update(member, before, after):
    async with voice_lock:
        voice_state = member.guild.voice_client
        
        if voice_state is not None and voice_state.is_connected():
            if len(voice_state.channel.members) == 1:
                if voice_state.is_playing():
                    voice_state.stop()
                await voice_state.disconnect()

client.run(bot_token)
