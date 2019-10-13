import asyncio
import threading
import logging

import aiohttp

from bot import Music
from config import Config
from websocket_client import ws_ctrl, ws_music

logging.basicConfig(
                level=logging.DEBUG,
                format='[%(asctime)s][%(module)s] %(message)s'
            )

async def main(loop):
    player_queue = asyncio.Queue()
    res_queue = asyncio.Queue()
    ctrl_queue = asyncio.Queue()
    key: dict = {}

    config = Config('config/config.json', 'config/alias.json', 'config/blacklist.json', 'config/ops.json')
    session = aiohttp.ClientSession()

    discord = threading.Thread(target=discord_loader, args=(config, player_queue, res_queue, ctrl_queue, loop),name='discord',  daemon=True)
    ctrl = threading.Thread(target=ctrl_loader, args=(ctrl_queue, res_queue, session, config.cmd_endpoint, key, loop), name='ctrl', daemon=True)
    music = threading.Thread(target=music_loader, args=(player_queue, session, config.stream_endpoint, key, loop), name='music', daemon=True)
    discord.start()
    ctrl.start()
    music.start()

def discord_loader(config, player_queue, res_queue, ctrl_queue, loop):
    asyncio.set_event_loop(loop)
    music = Music(config, player_queue, res_queue, ctrl_queue, loop)
    loop.create_task(music.start(config.token))

def ctrl_loader(q1, q2, session, uri, key, loop):
    asyncio.set_event_loop(loop)
    ws = ws_ctrl(q1, q2, session, uri, key, loop)
    loop.create_task(ws.receive_res())

def music_loader(q, session, uri, key, loop):
    asyncio.set_event_loop(loop)
    ws = ws_music(q, session, uri, key)
    loop.create_task(ws.receive_music_bin())

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.create_task(main(loop))

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        loop.close()
