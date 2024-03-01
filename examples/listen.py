import asyncio
import sys
import textwrap

import discord_ws

import logging

logging.basicConfig(
    format="%(name)30s (%(levelname)8s) => %(message)s",
)
logging.getLogger("discord_ws.client.client").setLevel(logging.DEBUG)
logging.getLogger("discord_ws.client.heartbeat").setLevel(logging.DEBUG)

TOKEN = "YOUR_TOKEN_HERE"
MAX_LENGTH = 100
# MAX_LENGTH = sys.maxsize

client = discord_ws.Client(
    token=TOKEN,
    intents=discord_ws.Intents.standard(),
)


@client.on_dispatch
async def handle_event(event: discord_ws.DispatchEvent):
    data = textwrap.shorten(str(event["d"]), MAX_LENGTH, placeholder="...")
    print(event["t"], "->", data)


if __name__ == "__main__":
    try:
        asyncio.run(client.run())
    except KeyboardInterrupt:
        pass
