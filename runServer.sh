#!/bin/bash

botCode="$1"
url="$2"
prefix="$3"

echo "Configuring bot settings..."

# Prepare config.txt from downloaded base template
cp config.txt config_working.txt

sed -i "s/BOT_TOKEN_HERE/$botCode/g" config_working.txt
sed -i "s,URL_PATH,$url,g" config_working.txt
sed -i "s/PREFIX/$prefix/g" config_working.txt

# Overwrite config.txt so viking.py can read it
mv config_working.txt config.txt

echo "Starting Viking Bot..."
exec python3 viking.py
