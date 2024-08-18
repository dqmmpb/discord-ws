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
logging.getLogger("discord_ws.client.stream").setLevel(logging.DEBUG)

TOKEN = "YOUR_TOKEN_HERE"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
MAX_LENGTH = 10000
# MAX_LENGTH = sys.maxsize

client = discord_ws.Client(
    token=TOKEN,
    intents=discord_ws.Intents.all(),
    user_agent=USER_AGENT,
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
