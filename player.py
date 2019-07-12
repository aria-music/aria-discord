import asyncio
import threading

import discord

from opus_loader import load_opus_libs

lock = asyncio.Lock()

def play(player_queue, vc, loop):
    asyncio.set_event_loop(loop)
    loop.create_task(_play(player_queue, vc))


async def _play(player_queue, vc):

    async def _wait_packet():
        '''
        音声パケットがplayer_queueにたまるまで10msスリープ
        '''
        await asyncio.sleep(0.01)

    count = 0
    output: bytearray = []
    while True:
        await lock.acquire()
        if player_queue.empty():
            lock.release()
            await asyncio.wait_for(_wait_packet(), timeout=0.5)
            continue
        else:
            data = player_queue.get_nowait()
            lock.release()
            count += 1
            output.append(data)

        if count == 10:
            for s in output:
                vc.send_audio_packet(s, encode=False)
            count = 0
            output.clear()
