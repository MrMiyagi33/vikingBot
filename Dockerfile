FROM gorialis/discord.py

ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /vikingbot

RUN apt-get update && apt-get install -y \
    wget \
    vim \
    ffmpeg \
    python3 \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# yt-dlp turns YouTube links and searches into audio streams; the deno extra is the
# JavaScript runtime yt-dlp needs for YouTube. --upgrade matters: old yt-dlp versions stop working.
RUN pip install --no-cache-dir --upgrade "discord.py[voice]" PyNaCl "yt-dlp[default,deno]"

RUN wget https://raw.githubusercontent.com/MrMiyagi33/vikingBot/refs/heads/main/viking.py \
    && wget https://raw.githubusercontent.com/MrMiyagi33/vikingBot/refs/heads/main/config.txt \
    && wget https://raw.githubusercontent.com/MrMiyagi33/vikingBot/refs/heads/main/runServer.sh \
    && chmod +x runServer.sh

ENV BOTCODE=''
ENV URL='https://storage.googleapis.com/udio-artifacts-c33fe3ba-3ffe-471f-92c8-5dfef90b3ea3/samples/c7ae67096a47484098b82bfb78f17e5f/2/Brothers%2520in%2520Valheim%2520ext%2520v2.1.1.2.mp3'
ENV PREFIX='>'

# Execute shell at runtime so environment variables are dynamically injected
ENTRYPOINT ["sh", "-c", "./runServer.sh \"$BOTCODE\" \"$URL\" \"$PREFIX\""]
