import asyncio
import collections
import os
import platform
from dataclasses import dataclass, replace
from typing import Optional
from urllib.parse import unquote, urlparse

import discord
import yt_dlp
from discord.ext import commands

intents = discord.Intents.all()

tokens = []
with open('config.txt') as file:
    for line in file:
        line = line.strip()
        if line:
            # Split on the first '=' only, so URLs like youtube.com/watch?v=... survive
            items = [item.strip() for item in line.split('=', 1)]
            tokens.append(items[1])

bot_token = tokens[0]
default_url = tokens[1]
prefix = tokens[2]

# DISABLE_VALHEIM_SONG=true stops the Valheim song playing, both when someone starts
# Valheim and when >play is used with nothing after it
valheim_song_disabled = os.environ.get('DISABLE_VALHEIM_SONG', '').strip().lower() in ('1', 'true', 'yes', 'on')

ffmpeg_path = 'ffmpeg.exe' if platform.system() == 'Windows' else 'ffmpeg'
ffprobe_path = 'ffprobe.exe' if platform.system() == 'Windows' else 'ffprobe'

YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'playlist_items': '1',
    'quiet': True,
    'no_warnings': True,
}

# Reconnect options stop long YouTube streams from cutting out part-way through
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

YOUTUBE_HOSTS = ('youtube.com', 'youtu.be')

client = commands.Bot(command_prefix=prefix, intents=intents)
voice_lock = asyncio.Lock()


@dataclass
class Track:
    title: str
    url: str                                     # YouTube page link, or a direct audio URL
    is_youtube: bool
    duration: Optional[int] = None               # seconds
    channel: Optional[discord.abc.Messageable] = None  # where to announce it, if anywhere
    start: Optional[float] = None                # seconds in to start from, when seeking


# guild id -> tracks waiting to play
queues = collections.defaultdict(collections.deque)
# guild id -> track playing now
now_playing = {}


def is_link(text):
    return text.startswith(('http://', 'https://'))


def file_title(url):
    """The file name from an audio link, e.g. '.../Brothers%2520in%2520Valheim.mp3' -> 'Brothers in Valheim.mp3'."""
    name = urlparse(url).path.rsplit('/', 1)[-1]
    # Some links are encoded twice (%2520), so decode until nothing changes
    while unquote(name) != name:
        name = unquote(name)
    return name or url


def default_track(channel=None):
    title = "default track" if is_youtube_link(default_url) else file_title(default_url)
    return Track(title=title, url=default_url, is_youtube=is_youtube_link(default_url), channel=channel)


def is_youtube_link(url):
    host = urlparse(url).netloc.lower()
    return any(host == h or host.endswith('.' + h) for h in YOUTUBE_HOSTS)


def format_time(seconds):
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02}:{seconds:02}"
    return f"{minutes}:{seconds:02}"


def format_duration(seconds):
    return f" ({format_time(seconds)})" if seconds else ''


def parse_time(text):
    """'90', '1:30' or '1:02:03' -> seconds, or None if it isn't a time."""
    parts = text.split(':')
    if len(parts) > 3 or not all(part.isdigit() for part in parts):
        return None
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + int(part)
    return seconds


class TrackedAudio(discord.PCMVolumeTransformer):
    """Counts the audio handed to Discord, so we know how far into the track we are."""

    def __init__(self, original, start=0):
        super().__init__(original)
        self.start = start
        self.frames = 0

    def read(self):
        data = super().read()
        if data:
            self.frames += 1
        return data

    @property
    def position(self):
        return self.start + self.frames * discord.opus.Encoder.FRAME_LENGTH / 1000


def _ytdl_extract(query):
    with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ydl:
        info = ydl.extract_info(query, download=False)
    # Searches (and playlist links) come back as a list; take the first result
    if info and 'entries' in info:
        entries = [entry for entry in info['entries'] if entry]
        info = entries[0] if entries else None
    return info


async def ytdl_extract(query):
    # yt-dlp blocks, so run it off the event loop or the whole bot freezes
    return await asyncio.to_thread(_ytdl_extract, query)


async def make_track(query, channel=None):
    """Turns a link or search words into a Track, or None if nothing was found."""
    if is_link(query) and not is_youtube_link(query):
        return Track(title=file_title(query), url=query, is_youtube=False, channel=channel)

    search = query if is_link(query) else f"ytsearch1:{query}"
    try:
        info = await ytdl_extract(search)
    except Exception as e:
        print(f"Could not look up {query}: {e}")
        return None
    if not info:
        return None
    page_url = info.get('webpage_url') or info.get('original_url') or query
    return Track(
        title=info.get('title') or page_url,
        url=page_url,
        is_youtube=True,
        duration=info.get('duration'),
        channel=channel,
    )


async def probe_duration(url):
    """Asks ffprobe how long an audio file is, in seconds, or None if it can't tell."""
    try:
        proc = await asyncio.create_subprocess_exec(
            ffprobe_path, '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', url,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        return float(out.decode().strip())
    except Exception as e:
        print(f"Could not get the length of {url}: {e}")
        return None


async def fill_in_details(track):
    """Looks up the length (and, for YouTube, the title) of a track that doesn't have them yet."""
    if track.duration:
        return
    if not track.is_youtube:
        track.duration = await probe_duration(track.url)
        return
    try:
        info = await ytdl_extract(track.url)
    except Exception as e:
        print(f"Could not look up {track.url}: {e}")
        return
    if info:
        track.title = info.get('title') or track.title
        track.duration = info.get('duration')


async def stream_url_for(track):
    # YouTube stream URLs expire after a few hours, so fetch a fresh one right before playing
    if not track.is_youtube:
        return track.url
    info = await ytdl_extract(track.url)
    if not info or not info.get('url'):
        raise RuntimeError("no audio stream found")
    return info['url']


async def send(channel, text):
    if channel is None:
        return
    try:
        await channel.send(text)
    except Exception as e:
        print(f"Could not send message: {e}")


def after_playing(error, guild):
    if error:
        print(f"Player error: {error}")

    fut = asyncio.run_coroutine_threadsafe(play_next(guild), client.loop)
    fut.add_done_callback(_report_future_error)


def _report_future_error(fut):
    try:
        fut.result()
    except Exception as e:
        print(f"Error starting next track: {e}")


async def play_next(guild):
    """Plays the next queued track, or leaves the channel once the queue is empty."""
    async with voice_lock:
        voice = guild.voice_client
        if voice is None or not voice.is_connected():
            queues[guild.id].clear()
            now_playing.pop(guild.id, None)
            return
        if voice.is_playing() or voice.is_paused():
            return

        queue = queues[guild.id]
        while queue:
            track = queue.popleft()
            now_playing[guild.id] = track
            try:
                stream_url = await stream_url_for(track)
                before_options = FFMPEG_OPTIONS['before_options']
                if track.start:
                    before_options = f"-ss {track.start:.2f} {before_options}"
                source = discord.FFmpegPCMAudio(stream_url, executable=ffmpeg_path,
                                                before_options=before_options, options=FFMPEG_OPTIONS['options'])
                voice.play(TrackedAudio(source, start=track.start or 0), after=lambda e: after_playing(e, guild))
            except Exception as e:
                print(f"Error playing {track.url}: {e}")
                await send(track.channel, f"Couldn't play **{track.title}**, skipping it.")
                continue
            if track.start is not None:
                await send(track.channel, f"Jumped to {format_time(track.start)} in **{track.title}**")
            else:
                await send(track.channel, f"Now playing **{track.title}**{format_duration(track.duration)}")
            return

        now_playing.pop(guild.id, None)
        await voice.disconnect()


async def connect_to(guild, voice_channel):
    """Joins (or moves to) the voice channel. Returns False if it couldn't."""
    async with voice_lock:
        voice = guild.voice_client
        try:
            if voice is None or not voice.is_connected():
                await voice_channel.connect(timeout=15.0, reconnect=True, self_deaf=True)
            elif voice.channel != voice_channel:
                await voice.move_to(voice_channel)
        except Exception as e:
            print(f"Failed to connect to voice channel: {e}")
            return False
        return True


def is_busy(guild):
    # now_playing is set as soon as a track is picked, so a track still being
    # looked up counts too
    voice = guild.voice_client
    playing = voice is not None and (voice.is_playing() or voice.is_paused())
    return playing or guild.id in now_playing or bool(queues[guild.id])


async def enqueue(guild, voice_channel, track):
    """Adds a track to the guild's queue and starts playing if nothing is.
    Returns the track's place in the queue (0 = playing now), or None on failure."""
    if not await connect_to(guild, voice_channel):
        return None
    was_busy = is_busy(guild)
    queues[guild.id].append(track)
    if was_busy:
        return len(queues[guild.id])
    await play_next(guild)
    return 0


@client.event
async def on_ready():
    print(f"Logged in as {client.user.name}")


@client.event
async def on_message(message):
    if message.author.bot:
        return
    await client.process_commands(message)


# >play [link or search words]
@client.command(name='play')
async def play_command(ctx, *, query: str = None):
    if ctx.author.voice is None or ctx.author.voice.channel is None:
        await ctx.send("You need to be in a voice channel to use this command!")
        return

    voice_channel = ctx.author.voice.channel
    if query:
        query = query.strip('<>')  # Discord's <link> form, used to hide the embed
        async with ctx.typing():
            track = await make_track(query, channel=ctx.channel)
        if track is None:
            await ctx.send(f"Couldn't find anything for **{query}**.")
            return
    elif valheim_song_disabled:
        await ctx.send(f"The Valheim song is turned off. Use `{prefix}play <YouTube link or search words>` to play something.")
        return
    else:
        track = default_track(channel=ctx.channel)

    position = await enqueue(ctx.guild, voice_channel, track)
    if position is None:
        await ctx.send("Failed to join channel or stream audio.")
    elif position > 0:
        await ctx.send(f"Queued **{track.title}**{format_duration(track.duration)} (#{position} in the queue)")


@client.command(name='skip')
async def skip_command(ctx):
    voice = ctx.guild.voice_client
    if voice is None or not (voice.is_playing() or voice.is_paused()):
        await ctx.send("Nothing is playing.")
        return
    track = now_playing.get(ctx.guild.id)
    # Stopping fires the after-callback, which starts the next track
    voice.stop()
    await ctx.send(f"Skipped **{track.title}**." if track else "Skipped.")


@client.command(name='pause')
async def pause_command(ctx):
    voice = ctx.guild.voice_client
    if voice is not None and voice.is_paused():
        await ctx.send(f"Already paused. Use `{prefix}resume` to keep listening.")
        return
    if voice is None or not voice.is_playing():
        await ctx.send("Nothing is playing.")
        return
    voice.pause()
    track = now_playing.get(ctx.guild.id)
    await ctx.send(f"Paused **{track.title}**." if track else "Paused.")


@client.command(name='resume')
async def resume_command(ctx):
    voice = ctx.guild.voice_client
    if voice is None or not voice.is_paused():
        await ctx.send("Nothing is paused.")
        return
    voice.resume()
    track = now_playing.get(ctx.guild.id)
    await ctx.send(f"Resumed **{track.title}**." if track else "Resumed.")


# >seek 1:30 jumps to 1:30, >seek +30 / >seek -30 jumps 30 seconds forward / back
@client.command(name='seek')
async def seek_command(ctx, *, when: str = ''):
    when = when.strip()
    sign = when[0] if when.startswith(('+', '-')) else ''
    seconds = parse_time(when[len(sign):].strip())
    if seconds is None:
        await ctx.send(f"Use `{prefix}seek 1:30` to jump to a time, or `{prefix}seek +30` / `{prefix}seek -30` "
                       f"to jump forward or back that many seconds.")
        return

    async with voice_lock:
        voice = ctx.guild.voice_client
        track = now_playing.get(ctx.guild.id)
        if (voice is None or track is None or not isinstance(voice.source, TrackedAudio)
                or not (voice.is_playing() or voice.is_paused())):
            await ctx.send("Nothing is playing.")
            return

        position = voice.source.position
        target = position + seconds if sign == '+' else position - seconds if sign == '-' else seconds
        target = max(0, target)
        if track.duration and target >= track.duration:
            await ctx.send(f"**{track.title}** is only {format_time(track.duration)} long.")
            return

        # Restart the track from the new spot: put it back at the front of the queue
        # and stop, and the after-callback plays it once we let go of the lock
        queues[ctx.guild.id].appendleft(replace(track, start=target, channel=ctx.channel))
        voice.stop()


# >nowplaying (or >np) shows the song, how far into it we are and how long is left
@client.command(name='nowplaying', aliases=['np'])
async def nowplaying_command(ctx):
    voice = ctx.guild.voice_client
    track = now_playing.get(ctx.guild.id)
    if voice is None or track is None or not isinstance(voice.source, TrackedAudio):
        await ctx.send("Nothing is playing.")
        return

    await fill_in_details(track)
    position = voice.source.position
    paused = " (paused)" if voice.is_paused() else ""
    if track.duration:
        left = max(0, track.duration - position)
        await ctx.send(f"**{track.title}**{paused}\n{format_time(position)} / {format_time(track.duration)}"
                       f" ({format_time(left)} left)")
    else:
        await ctx.send(f"**{track.title}**{paused}\n{format_time(position)} (length unknown)")


@client.command(name='queue')
async def queue_command(ctx):
    track = now_playing.get(ctx.guild.id)
    queue = queues[ctx.guild.id]
    if track is None and not queue:
        await ctx.send("The queue is empty.")
        return

    lines = []
    if track:
        voice = ctx.guild.voice_client
        label = "Paused" if voice is not None and voice.is_paused() else "Now playing"
        lines.append(f"{label}: **{track.title}**{format_duration(track.duration)}")
    for i, queued in enumerate(list(queue)[:10], start=1):
        lines.append(f"{i}. {queued.title}{format_duration(queued.duration)}")
    if len(queue) > 10:
        lines.append(f"...and {len(queue) - 10} more")
    await ctx.send("\n".join(lines))


@client.command(name='stop')
async def stop_command(ctx):
    voice = ctx.guild.voice_client
    queues[ctx.guild.id].clear()
    now_playing.pop(ctx.guild.id, None)
    if voice and voice.is_connected():
        if voice.is_playing() or voice.is_paused():
            voice.stop()
        await voice.disconnect()
        await ctx.send("Cleared the queue and disconnected from voice channel.")
    else:
        await ctx.send("I am not connected to a voice channel.")


@client.event
async def on_presence_update(before, after):
    if valheim_song_disabled:
        return
    if str(before.activity) == str(after.activity):
        return

    if (
        after.activity is not None
        and str(after.activity.name) == 'Valheim'
        and after.voice is not None
        and after.voice.channel is not None
    ):
        # Don't interrupt or pile onto music people queued up
        if is_busy(after.guild):
            return
        track = default_track()
        await enqueue(after.guild, after.voice.channel, track)


@client.event
async def on_voice_state_update(member, before, after):
    async with voice_lock:
        voice_state = member.guild.voice_client
        if voice_state is not None and voice_state.is_connected():
            if len(voice_state.channel.members) == 1:
                queues[member.guild.id].clear()
                if voice_state.is_playing() or voice_state.is_paused():
                    voice_state.stop()
                await voice_state.disconnect()


client.run(bot_token)
