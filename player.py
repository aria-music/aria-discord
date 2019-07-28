import asyncio
import threading

import discord

from opus_loader import load_opus_libs

lock = asyncio.Lock()

def play(player_queue, vc, loop):
    count = 0
    output: bytearray = []
    vc.loop.create_task(_play(player_queue, vc, count, output))


async def _play(player_queue, vc, count, output):
    await lock.acquire()
    if player_queue.empty():
        lock.release()
        await asyncio.sleep(0.01)
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
    vc.loop.create_task(_play(player_queue, vc, count, output))
