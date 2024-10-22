#!/bin/bash

botCode="$1"
echo "bot code: "$botCode
url="$2"
echo "url: "$url
prefix="$3"
echo "prefix: "$prefix

sed -i "s/BOT_TOKEN_HERE/$botCode/g" config.txt
sed -i "s/URL/$url/g" config.txt
sed -i "s/PREFIX/$prefix/g" config.txt

py viking.py