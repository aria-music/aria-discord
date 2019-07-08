import asyncio
import aiohttp
import threading
import json
import logging

lock = asyncio.Lock()
event = threading.Event()

class ws_ctrl():
    def __init__(self, ctrl_queue, res_queue, session, uri, key, loop):
        self.ctrl_queue = ctrl_queue
        self.res_queue = res_queue
        self.session = session
        self.uri = uri
        self.global_key = key
        self.key = None
        self.loop = loop

    async def post_op(self, wsclient):
        op = ''
        async with lock:
            if not self.ctrl_queue.empty():
                op = self.ctrl_queue.get_nowait()

        if op:
            if op[0] == 'discord ready':
                event.set()
            else:
                await wsclient.send_json(enclose_packet(op[0], self.key, op[1]))
                logging.info(f'post: {op}')
        await asyncio.sleep(0.5)
        self.loop.create_task(self.post_op(wsclient))

    async def receive_res(self):
        wsclient = await self.session.ws_connect(self.uri)
        logging.info('res ws connected')
        async for msg in wsclient:
            res = json.loads(msg.data)
            if res.get('type') == 'hello':
                async with lock:
                    self.global_key['key'] = res.get('key')
                self.key = res.get('key')
                logging.info(f'ws key: {self.key}')
                self.loop.create_task(self.post_op(wsclient))
            else:
                async with lock:
                    self.res_queue.put_nowait(res)

class ws_music():
    def __init__(self, player_queue, session, uri, key):
        self.player_queue = player_queue
        self.session = session
        self.uri = uri
        self.key = key

    async def receive_music_bin(self):
        while not event.wait(timeout=0.5):
            await asyncio.sleep(1)

        async with self.session.ws_connect(self.uri) as wsclient:
            async with lock:
                key = self.key.get('key')

            await wsclient.send_str(key)
            logging.info('music ws connected')
            async for msg in wsclient:
                logging.debug(msg.data)
                if msg.type == aiohttp.WSMsgType.ERROR:
                    break
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    async with lock:
                        self.player_queue.put_nowait(msg.data)

def enclose_packet(op, key, data=None):
    return {
        'op': op,
        'key': key,
        'data': data
    }
