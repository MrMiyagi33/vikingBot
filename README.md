# vikingBot
Discord bot that play an valheim themed song when you start Valheim in a voice channel

It also plays music from YouTube, with a queue:

- `>play <YouTube link or search words>` - adds a song to the queue (plays straight away if nothing is playing)
- `>play <link to an audio file>` - same, for a direct audio link (like an .mp3)
- `>play` - queues the default Valheim song
- `>pause` - pauses the current song
- `>resume` - carries on playing a paused song
- `>seek 1:30` - jumps to 1:30 in the current song
- `>seek +30` / `>seek -30` - jumps forward / back 30 seconds
- `>np` (or `>nowplaying`) - shows the song playing, the time into it and the time left
- `>skip` - skips to the next song
- `>queue` - shows what's playing and what's next
- `>stop` - clears the queue and leaves the voice channel

Starting Valheim only plays the theme when the bot isn't already playing something.

YouTube changes often and old yt-dlp versions stop working, so rebuild the Docker image if songs stop playing.
