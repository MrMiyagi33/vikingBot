FROM gorialis/discord.py

ENV DEBIAN_FRONTEND=noninteractive

VOLUME [ "/vikingbot" ]

WORKDIR /vikingbot

ENV BOTCODE=''
ENV URL='https://storage.googleapis.com/udio-artifacts-c33fe3ba-3ffe-471f-92c8-5dfef90b3ea3/samples/c7ae67096a47484098b82bfb78f17e5f/2/Brothers%2520in%2520Valheim%2520ext%2520v2.1.1.2.mp3'
ENV PREFIX='>'

RUN apt-get update && apt-get install -y \
    wget \
    vim \
    ffmpeg \
    python3 \
    && rm -rf /var/lib/apt/lists/*

RUN wget https://raw.githubusercontent.com/MrMiyagi33/vikingBot/refs/heads/main/viking.py \
    && wget https://raw.githubusercontent.com/MrMiyagi33/vikingBot/refs/heads/main/config.txt \
    && wget https://raw.githubusercontent.com/MrMiyagi33/vikingBot/refs/heads/main/runServer.sh

ENTRYPOINT sh runServer.sh "$BOTCODE" "$URL" "$PREFIX"