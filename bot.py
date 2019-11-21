import asyncio
import json
import logging
import random
import re
import textwrap
import threading
from sys import argv

import discord
from config import Config
from opus_loader import load_opus_libs

lock = asyncio.Lock()

class Music(discord.Client):
    def __init__(self, config, player_queue, res_queue, ctrl_queue, loop):
        super().__init__()
        load_opus_libs()
        self.config = config
        self.player_queue = player_queue
        self.res_queue = res_queue
        self.ctrl_queue = ctrl_queue
        self.loop = loop
        self.voice = None
        self.vc_members = 0

        self.player_status = {
            'state': False,
            'source': None,
            'title': None,
            'album': None,
            'artist': None,
            'uri': None,
            'is_liked': False,
            'duration': None,
            'position': None
        }
        self.play_queue = {}

        self.nums = [
            ':one:',
            ':two:',
            ':three:',
            ':four:',
            ':five:',
            ':six:',
            ':seven:',
            ':eight:',
            ':nine:'
        ]
        self.unicode_nums = [
            '\U00000031\U000020E3',
            '\U00000032\U000020E3',
            '\U00000033\U000020E3',
            '\U00000034\U000020E3',
            '\U00000035\U000020E3',
            '\U00000036\U000020E3',
            '\U00000037\U000020E3',
            '\U00000038\U000020E3',
            '\U00000039\U000020E3'
        ]
        self.inv_unicode_nums = {
            '\U00000031\U000020E3': 1,
            '\U00000032\U000020E3': 2,
            '\U00000033\U000020E3': 3,
            '\U00000034\U000020E3': 4,
            '\U00000035\U000020E3': 5,
            '\U00000036\U000020E3': 6,
            '\U00000037\U000020E3': 7,
            '\U00000038\U000020E3': 8,
            '\U00000039\U000020E3': 9
        }
        self.control = {
            'fast_forward': '\U000023E9',
            'rewind': '\U000023EA',
            'ok': '\U0001F197',
            'no_entry_sign': '\U0001F6AB',
            'white_check_mark': '\U00002705',
            'play_all': '\U0001F35C'
        }

    async def on_ready(self):
        logging.info('connected to discord')
        #await asyncio.wait_for(self.join_vc(), timeout=5.0)
        await self.join_vc()
        await self.post('discord ready')
        logging.info('discord vc connect')
        response_handler = threading.Thread(target=self.handle_res, daemon=True)
        self.vc_members = len(self.voice.channel.members)
        self.loop.create_task(self._play())

        response_handler.start()
        logging.info('connected to vc')

    async def safe_send(self, dest, payload, users=None):
        '''
        Parameters
        ----------
        dest: discord.channel.TextChannel
        payload: str
        user: message.author

        Returns
        -------
        msg
        '''
        try:
            if users:
                if not isinstance(users, (list, tuple)):
                    users = [users]
                msg = await dest.send(f'{" ".join([user.mention for user in users])}\n{payload}')
            else:
                msg = await dest.send(payload)
        except discord.Forbidden:
            logging.error('You do not have the proper permissions to send the message.')
            return None
        except discord.NotFound:
            logging.error('dest channel is not found')
            return None
        except discord.HTTPException:
            logging.error('Sending the message failed.')
            return None
        return msg

    async def safe_delete(self, message):
        try:
            return await message.delete()
        except discord.Forbidden:
            logging.error('cannot delete message: no permission')
        except discord.NotFound:
            logging.error('cannot delete message: message not found')

    async def join_vc(self):
        self.voice_channel = self.get_channel(self.config.voice_channel_id)
        self.voice = await self.voice_channel.connect()

    async def exit_vc(self):
        await self.voice.disconnect()
        self.voice = None

    async def cmd_reconnect(self, message=None, dest=None, cmd_args=[]):
        try:
            await asyncio.wait_for(self.exit_vc(), timeout=0.2)
        except TimeoutError:
            logging.error('TimeoutError')
            return
        await self.join_vc()

    async def on_voice_state_update(self, member, before, after):
        if not self.voice:
            return
        if self.vc_members != len(self.voice.channel.members):
            if self.vc_members < len(self.voice.channel.members):
                await self.cmd_reconnect()
            self.vc_members = len(self.voice.channel.members)

    async def post(self, op, data=None, postback=None):
        '''
        post op and message
        '''
        async with lock:
            self.ctrl_queue.put_nowait((op, data, postback))

    async def set_game_activity(self):
        '''
        update game activity
        '''
        song = ''
        if self.player_status.get('state') != 'playing':
            song = u'\u275A\u275A'

        if self.player_status.get('is_liked'):
            song += u'\u2665 '

        if self.player_status.get('title'):
            song += f'{self.player_status.get("title")}'

        if self.player_status.get('artist'):
            song += f' / {self.player_status.get("artist")}'


        playing_status = discord.Game(name=song)
        await self.change_presence(activity=playing_status)

    async def _play(self):
        await lock.acquire()
        if self.player_queue.empty():
            lock.release()
            await asyncio.sleep(0.001)
        else:
            if self.voice:
                self.voice.send_audio_packet(self.player_queue.get_nowait(), encode=False)
            lock.release()
        self.loop.create_task(self._play())

    def handle_res(self):
        self.loop.create_task(self._handle_res())

    async def _handle_res(self):
        res = await self.res_queue.get()
        response_type = res.get('type')
        if response_type == 'search':
            self.loop.create_task(self.search(res))
        elif response_type == 'list_queue':
            self.loop.create_task(self.set_play_queue(res))
        elif response_type == 'state':
            self.loop.create_task(self.show_np(res))
        elif response_type == 'playlists':
            self.loop.create_task(self.show_playlists(res))
        elif response_type == 'playlist':
            self.loop.create_task(self.show_likelen(res))
        elif response_type == 'token':
            self.loop.create_task(self.show_token(res))
        elif response_type == 'event_player_state_change':
            self.loop.create_task(self.set_player_status(res))
        elif response_type == 'event_queue_change':
            self.loop.create_task(self.set_play_queue(res))
        elif response_type == 'event_playlists_change':
            pass
        elif response_type == 'event_playlist_entry_change':
            pass
        else:
            logging.warning('error: unexpected response type')

        self.loop.create_task(self._handle_res())

    async def set_player_status(self, res):
        '''
        update self.player_status
        '''
        data = res.get('data')
        self.player_status['state'] = data.get('state')
        entry = data.get('entry')
        if entry:
            self.player_status['source'] = entry.get('source')
            self.player_status['title'] = entry.get('title')
            self.player_status['uri'] = entry.get('uri')
            self.player_status['is_liked'] = entry.get('is_liked')
            self.player_status['duration'] = entry.get('duration')
            self.player_status['position'] = entry.get('position')
            if self.player_status['source'] == 'gpm':
                self.player_status['title'] = entry.get('entry').get('title')
                self.player_status['album'] = entry.get('entry').get('album')
                self.player_status['artist'] = entry.get('entry').get('artist')
                self.player_status['user'] = entry.get('entry').get('user')
            else:
                self.player_status['album'] = None
                self.player_status['artist'] = None
        else:
            self.player_status['source'] = None
            self.player_status['title'] = None
            self.player_status['title'] = None
            self.player_status['album'] = None
            self.player_status['artist'] = None
            self.player_status['user'] = None
            self.player_status['uri'] = None
            self.player_status['is_liked'] = False
            self.player_status['duration'] = None
            self.player_status['position'] = None

        await self.set_game_activity()

        if self.player_status['state'] == 'stopped':
            await lock.acquire()
            while not self.player_queue.empty():
                self.player_queue.get_nowait()
            lock.release()

    async def set_play_queue(self, res):
        '''
        update self.player_queue
        '''
        self.play_queue = res

    async def search(self, raw_result):
        '''
        search

        Parameters
        ----------
        raw_result: dict
        '''
        dest = self.get_channel(raw_result.get('postback') or self.config.text_channel_id)
        results = await self.parse_result(raw_result)
        if not results:
            res_text = f'Sorry\ncould not find any track'
            await self.safe_send(dest, res_text)
            return

        res_text = (f'**search result**\n'
                    f'**{len(results)}** hits')
        await self.safe_send(dest, res_text)

        res_count = self.config.serch_result_count
        total_page = -(-len(results) // res_count)
        result = results
        to_play = []

        async def _send():
            if to_play:
                if len(to_play) == 1:
                    await self.post('queue', {'uri': to_play[0]})
                else:
                    await self.post('queue', {'uri': to_play})

        for page in range(total_page):
            res_text = f'page: {page+1} / {total_page}\n'
            show = result[0:len(result) if len(result) < res_count else res_count]
            result = result[len(result) if len(result) < res_count else res_count:]
            res_text += await self.format_list(show, 'search')
            #r = re.compile(key, re.IGNORECASE)
            #res_text = re.sub(r, f'**{key}**', res_text)
            msg = await self.safe_send(dest, res_text)

            for i in range(len(show)):
                await msg.add_reaction(self.unicode_nums[i])
            if page+1 != total_page:
                await msg.add_reaction(self.control['fast_forward'])
            for i in ['no_entry_sign', 'white_check_mark', 'play_all']:
                await msg.add_reaction(self.control[i])

            def check(reaction, user):
                return user != msg.author and reaction.message.id == msg.id

            next_page = False
            while True:
                try:
                    reaction, _ = await self.wait_for('reaction_add', timeout=60.0, check=check)

                    if str(reaction.emoji) == self.control['fast_forward']: #go next page
                        await self.safe_delete(msg)
                        next_page = True
                        break
                    elif str(reaction.emoji) == self.control['no_entry_sign']: #cancel
                        await self.safe_delete(msg)
                        return
                    elif str(reaction.emoji) == self.control['white_check_mark']: #submit
                        await self.safe_delete(msg)
                        break
                    elif str(reaction.emoji) == self.control['play_all']: #play all
                        await self.safe_delete(msg)
                        to_play.clear()
                        to_play = [i[5] for i in results]
                        break

                    select = self.inv_unicode_nums.get(str(reaction.emoji))
                    if select:
                        to_play.append(show[select-1][4])
                except asyncio.TimeoutError:
                    await self.safe_delete(msg)
                    return

            if next_page and page != total_page:
                continue
            else:
                break

        await _send()
    """
    async def queue(self, raw_result):
        dest = self.get_channel(self.config.text_channel_id)
        result = await self.parse_queue(raw_result)
        if not result:
            res_text = f'No tracks in queue'
            await self.safe_send(dest, res_text)
            return
        res_text = (f'**play queue**\n'
                    f'**{len(result)}** tracks in queue')
        res_text = await self.format_list(result, 'queue')
        await self.safe_send(dest, res_text)
    """

    async def show_np(self, res):
        dest = self.get_channel(res.get('postback') or self.config.text_channel_id)
        try:
            await asyncio.wait_for(self.set_player_status(res), timeout=1.0)
            res_text = ''
            if self.player_status.get('state') == 'playing':
                res_text = f':arrow_forward: **{self.player_status.get("title")}\n\n**'
            else:
                res_text = f':pause_button: **{self.player_status.get("title")}\n\n**'
            if self.player_status.get('source') == 'gpm':
                res_text += (f'        album: **{self.player_status.get("album")}**\n'
                            f'        artist: **{self.player_status.get("artist")}**\n'
                            '        from: **gpm**\n'
                            f'        owner: **{self.player_status.get("user")}**\n'
                            f'        uri: {self.player_status.get("uri")}\n')
            else:
                res_text += (f'        from: **{self.player_status.get("source")}**\n'
                            f'        uri: <{self.player_status.get("uri")}>\n')

            def _format_time (song_len):
                return f'{int(song_len/60)}:{int(song_len%60)}'

            res_text += f'        position: {_format_time(self.player_status.get("position"))} / {_format_time(self.player_status.get("duration"))}'
            await self.safe_send(dest, res_text)
        except TimeoutError:
            logging.error('TimeoutError')
            return

    async def parse_result(self, res):
        '''
        parse json

        Parameters
        ----------
        res: dict

        Returns
        -------
        resp: list
        '''
        if res.get('data') == None:
            #0hit
            return None

        resp = []
        for entry in res.get('data'):
            source = entry.get('source')
            title = entry.get('title')
            uri = entry.get('uri')
            if source == 'gpm':
                gpm_info = [entry.get('entry').get(i) for i in ['title', 'album', 'artist', 'user']]
                gpm_info.insert(0, source)
                gpm_info.append(uri)
                resp.append(tuple(gpm_info))
            else:
                resp.append((source, title, None, None, uri))
        return resp

    async def parse_queue(self, res):
        '''
        fetch play que

        Paramters
        ---------
        res: dict

        Returns
        -------
        que: list
        '''
        if res.get('data').get('queue') == None:
            #no item in queue
            return None

        resp = []
        for entry in res.get('data').get('queue'):
            source = entry.get('source')
            title = entry.get('title')
            uri = entry.get('uri')
            if source == 'gpm':
                gpm_info = [entry.get('entry').get(i) for i in ['title', 'album', 'artist', 'user']]
                gpm_info.insert(0, source)
                gpm_info.append(uri)
                resp.append(tuple(gpm_info))
            else:
                resp.append((source, title, None, None, uri))
        return resp

    async def show_playlists(self, res):
        _playlists = {}
        dest = self.get_channel(res.get('postback') or self.config.text_channel_id)

        for entry in res.get('data').get('playlists'):
            _playlists[entry.get('name')] = entry.get('length')

        res_text = ''
        res_text = 'playlist\n\n'
        for i in _playlists:
            res_text += f':file_folder: **{i}** has **{_playlists[i]}** tracks :musical_note:\n'
        res_text += '\nmore info use web client'

        await self.safe_send(dest, res_text)

    async def show_likelen(self, res):
        dest = self.get_channel(res.get('postback') or self.config.text_channel_id)

        lenlist = len(res.get('data').get('entries'))

        await self.safe_send(dest, f'Likes has **{lenlist}** tracks :musical_note: \nmore info use web client')

    async def show_token(self, res):
        dest = self.get_channel(res.get('postback') or self.config.text_channel_id)
        token = res.get('data').get('token')
        msg_id = await self.safe_send(dest, f'Your TOKEN : **{token}**')
        await asyncio.sleep(60)
        await self.safe_delete(msg_id)

    async def gen_command_list(self):
        self.commandlist = []
        for attr in dir(self):
            if attr.startswith('cmd_'):
                self.commandlist.append(self.config.cmd_prefix+attr[4:])

    async def format_list(self, orig_list, opr):
        numberd_list = ''
        if opr == 'queue':
            if self.player_status.get('state') == 'playing':
                numberd_list = f':arrow_forward: **{self.player_status.get("title")}**\n'
            else:
                numberd_list = f':pause_button: **{self.player_status.get("title")}**\n'
            if self.player_status.get('source') == 'gpm':
                numberd_list += f'        {self.player_status.get("album")} / {self.player_status.get("artist")}\n\n'
            else:
                numberd_list += '\n\n'
            numberd_list += f'**{len(orig_list)}** tracks in queue\n\n'
        for num, song in zip(self.nums, orig_list):
            if song[0] == 'gpm':
                numberd_list += (f'{num} **{song[1]}**\n'
                                f'        {song[2]} / {song[3]}\n'
                                f"        from: gpm - {song[4]}\n")
            else:
                numberd_list += (f'{num} **{song[1]}**\n'
                                f'        - from: {song[0]}\n')

        return numberd_list

    def op_only(func):
        async def wrapper(self, *args, **kwargs):
            #print(args[0].author.id)
            if args[0].author.id in self.config.op:
                return await func(self, *args, **kwargs)
            else:
                return await self.safe_send(args[0].channel ,':regional_indicator_f: :regional_indicator_u: :regional_indicator_c: :regional_indicator_k: :regional_indicator_y: :regional_indicator_o: :regional_indicator_u:', args[0].author.mention)
        return wrapper
    ##########################
    async def cmd_play(self, message, dest, *cmd_args):
        '''
        play song from URL

        usage {prefix}play URL(s)
        '''
        if not cmd_args:
            await self.safe_send(dest, 'error:anger:\nusage: `{prefix}play URL`'.format(prefix=self.config.cmd_prefix))
            return
        if len(cmd_args) == 1:
            if cmd_args[0][0] == '<':
                await self.post('queue', {'uri':cmd_args[0][1:-1]}, dest.id)
            else:
                await self.post('queue', {'uri':cmd_args[0]}, dest.id)
        else:
            await self.post('queue', {'uri':[i if i[0] != '<' else i[1:-1] for i in cmd_args]}, dest.id)

    async def cmd_repeat(self, message, dest, *cmd_args):
        '''
        repeat now-playing song

        usage {prefix}repeat <num>
        '''
        if not cmd_args:
            await self.post('repeat', {'uri': self.player_status.get('uri')}, dest.id)
            return
        try:
            count = int(cmd_args[0])
            await self.post('repeat', {'uri': self.player_status.get('uri'), 'count': count}, dest.id)
        except ValueError:
            await self.post('repeat', {'uri': self.player_status.get('uri')}, dest.id)

    async def cmd_pause(self, message, dest, *cmd_args):
        '''
        pause

        usage {prefix}pause
        '''
        if not self.player_status.get('state') == 'playing':
            #pausing
            await dest.send('error:anger:\nplayer is already paused')
            return
        else:
            await self.post('pause', postback=dest.id)

    async def cmd_resume(self, message, dest, *cmd_args):
        '''
        resume

        usage {prefix}resume
        '''
        if self.player_status.get('state') == 'playing':
            #playing
            await dest.send('error:anger:\nplayer is already playing')
            return
        else:
            await self.post('resume', postback=dest.id)

    async def cmd_skip(self, message, dest, *cmd_args):
        '''
        skip

        usage {prefix}skip
        '''
        if not cmd_args:
            await self.post('skip', postback=dest.id)
            return
        await self.cmd_skip_to(message, dest, *cmd_args)

    async def cmd_skip_to(self, message, dest, *cmd_args):
        '''
        skip to selected entry

        usage {prefix}skip_to num
        '''
        if not cmd_args:
            await self.safe_send(dest, ('error:anger:\n'
                                        'If you want to skip this track, USE `{prefix}skip`\n'
                                        'usage `{prefix}skip_to num`'.format(prefix=self.config.cmd_prefix)))
            return
        try:
            index = int(cmd_args[0]) - 1
            if index <= len(self.play_queue.get('data').get('queue')):
                await self.post('skip_to', {'index': index, 'uri': self.play_queue.get('data').get('queue')[index].get('uri')}, dest.id)
            else:
                await self.safe_send(dest, f'{index+1} is out of queue range')
        except ValueError:
            await self.safe_send(dest, 'error:anger:\n usage `{prefix}skip_to num`'.format(prefix=self.config.cmd_prefix))

    async def cmd_queue(self, message, dest, *cmd_args):
        '''
        show song list in queue

        usage {prefix}queue
        '''
        result = await self.parse_queue(self.play_queue)
        if not result:
            res_text = f'No tracks in queue'
            await self.safe_send(dest, res_text)
            return
        res_text = (f'**play queue**\n'
                    f'**{len(result)}** tracks in queue')
        res_text = await self.format_list(result, 'queue')
        await self.safe_send(dest, res_text)


    async def cmd_playnext(self, message, dest, *cmd_args):
        '''
        play next

        usage {prefix}playnext URL
        '''
        if len(cmd_args) != 1:
            await dest.send('error:anger:\n usage `{prefix}playnext URL`'.format(prefix=self.config.cmd_prefix))
            return
        await self.post('queue', {'uri': cmd_args[0], 'head': True}, dest.id)

    async def cmd_add(self, message, dest, *cmd_args):
        '''
        store auto playlist

        usage {prefix}add URL(s)
        '''
        if not cmd_args:
            await dest.send('error:anger:\n usage `{prefix}add URL(s)`'.format(prefix=self.config.cmd_prefix))
            return
        if len(cmd_args) == 1:
            if cmd_args[0][0] == '<':
                await self.post('add_to_playlist', {'name': 'Likes', 'uri':cmd_args[0][1:-1]}, dest.id)
            else:
                await self.post('add_to_playlist', {'name': 'Likes', 'uri':cmd_args[0]}, dest.id)
        else:
            for i in cmd_args:
                if i[0] == '<':
                    await self.post('add_to_playlist', {'name': 'Likes', 'uri':i[1:-1]}, dest.id)
                else:
                    await self.post('add_to_playlist', {'name': 'Likes', 'uri':i}, dest.id)

    async def cmd_remove(self, message, dest, *cmd_args):
        '''
        remove from queue

        usage {prefix}remove num
        '''
        if not cmd_args:
            await dest.send('error:anger:\nusage `{prefix}remove URL(s)`'.format(prefix=self.config.cmd_prefix))
            return
        try:
            index = int(cmd_args[0]) - 1
            if index <= len(self.play_queue):
                await self.post('remove', {'index': index, 'uri': self.play_queue.get('data').get('queue')[index].get('uri')}, dest.id)
            else:
                await self.safe_send(dest, f'{index} is out of queue range')
        except ValueError:
            await self.safe_send(dest, 'error:anger:\n usage `{prefix}remove num`'.format(prefix=self.config.cmd_prefix))

    async def cmd_np(self, message, dest, *cmd_args):
        '''
        show song info

        usage {prefix}np
        '''
        await self.post('state', postback=dest.id)

    async def cmd_like(self, message, dest, *cmd_args):
        '''
        save current track to playlist [Likes]

        usage {prefix}like
        '''
        if not self.player_status.get('is_liked'):
            await self.post('like', {'uri': self.player_status.get('uri')}, dest.id)

    async def cmd_likes(self, message, dest, *cmd_args):
        '''
        show how many songs in playlist [Likes]

        usage {prefix}likes
        '''
        await self.post('playlist', {'name': 'Likes'}, dest.id)

    async def cmd_playlists(self, message, dest, *cmd_args):
        '''
        show playlists name

        usage {prefix}playlists
        '''
        await self.post('playlists', postback=dest.id)

    async def cmd_mklist(self, message, dest, *cmd_args):
        '''
        create playlist

        usage {prefix}mklist
        '''
        if not cmd_args:
            await self.safe_send(dest, 'error:anger:\nusage: `{prefix}play URL`'.format(prefix=self.config.cmd_prefix))
            return
        await self.post('create_playlist', {'name': cmd_args[0]}, dest.id)

    async def cmd_clear(self, message, dest, *cmd_args):
        '''
        clear queue

        usage {prefix}clear
        '''
        await self.post('clear_queue', postback=dest.id)

    async def cmd_shuffle(self, message, dest, *cmd_args):
        '''
        shuffle queue

        usage {prefix}shuffle
        '''
        await self.post('shuffle', postback=dest.id)

    async def cmd_purge(self, message, dest, *cmd_args):
        '''
        remove from auto playlist

        usage {prefix}purge URLs
        '''
        if not cmd_args:
            if self.player_status.get('is_liked'):
                await self.post('remove_from_playlist', {'name':'Likes', 'uri': self.player_status.get('uri')}, dest.id)
            else:
                await self.safe_send(dest, 'error:anger:\nThis track is not in Likes')
            return
        for url in cmd_args:
            await self.post('remove_from_playlist', {'name':'Likes', 'uri': url}, dest.id)

    async def cmd_save(self, message, dest, *cmd_args):
        '''
        save song into playlist

        usage {prefix}save
        '''
        if not cmd_args:
            await self.post('add_to_playlist', {'name': 'Likes', 'uri': self.player_status.get('uri')}, dest.id)
        else:
            for pl in cmd_args:
                await self.post('add_to_playlist', {'name': pl, 'uri': self.player_status.get('uri')}, dest.id)

    async def cmd_search(self, message, dest, *cmd_args):
        '''
        search song in youtube and gpm

        usage {prefix}search keyword
        '''
        await self._cmd_search(dest, None, cmd_args)

    async def cmd_gsearch(self, message, dest, *cmd_args):
        '''
        search song in gpm

        usage {prefix}gsearch keyword
        '''
        await self._cmd_search(dest, 'gpm', cmd_args)

    async def cmd_ysearch(self, message, dest, *cmd_args):
        '''
        search song in youtube

        usage {prefix}ysearch keyword
        '''
        await self._cmd_search(dest, 'youtube', cmd_args)

    async def _cmd_search(self, dest, provider, cmd_args):
        '''
        search
        '''
        if not cmd_args:
            await dest.send('error:anger:\nusage `{prefix}search keyword`'.format(prefix=self.config.cmd_prefix))
            return

        query = ' '.join(cmd_args)
        if provider:
            await self.post('search', {'query': query, 'provider': provider}, dest.id)
        else:
            await self.post('search', {'query': query}, dest.id)

    async def cmd_s(self, message, dest, *cmd_args):
        if not cmd_args:
            await self.post('skip', postback=dest.id)
            return
        try:
            int(cmd_args[0])
            await self.cmd_skip_to(message, dest, *cmd_args)
        except ValueError:
            await self.cmd_search(message, dest, *cmd_args)

    @op_only
    async def cmd_join(self, message, dest, *cmd_args):
        '''
        [operator only]join VC

        usage {prefix}join
        '''
        if self.voice:
            await dest.send(f'{self.user} is already in VC')
            return
        await self.join_vc()

    @op_only
    async def cmd_kick(self, message, dest, *cmd_args):
        '''
        [operator only]kick bot from VC

        usage {prefix}kick
        '''
        if not self.voice:
            await dest.send(f'{self.user} is not in VC')
            return
        await self.exit_vc()

    @op_only
    async def cmd_logout(self, message, dest, *cmd_args):
        '''
        [operator only]

        usage {prefix}logout
        '''
        await self.logout()
        exit(1)

    async def cmd_show_alias(self, message, dest, *cmd_args):
        '''
        show command alias

        usage {prefix}show_alias
        '''
        res_text = ''
        if self.config.alias:
            res_text = 'alias\n\n'
            for i in self.config.alias:
                res_text += f'`{i}` is`{self.config.alias[i]}`\n'
        else:
            res_text = 'command alias does not exist\nedit `config/alias.json`'
        await self.safe_send(dest, res_text)

    @op_only
    async def cmd_reload_alias(self, message, dest, *cmd_args):
        '''
        reload config/alias.json

        usage {prefix}reload_alias
        '''
        try:
            with open('config/alias.json', 'r') as f:
                self.config.alias = json.load(f)
            await self.safe_send(dest, 'alias is updated')
        except FileNotFoundError:
            logging.error('alias file does not exist')
            await self.safe_send(dest, 'alias file does not exist\nNo changed')

    async def cmd_fuck(self, message, dest, *cmd_args):
        '''
        F U C K Y O U
        '''
        await self.safe_delete(message)
        target = message.mentions or [message.author]
        fuck_str = ':regional_indicator_f: :regional_indicator_u: :regional_indicator_c: :regional_indicator_k: :regional_indicator_y: :regional_indicator_o: :regional_indicator_u: '
        await self.safe_send(dest, fuck_str, target)

    async def cmd_potg(self, message, dest, *cmd_args):
        await self.safe_delete(message)
        target = message.mentions or [message.author]
        potg_strs = [':right_facing_fist: :left_facing_fist: 推薦されました:チームプレイヤー', ':handshake: 推薦されました:スポーツマンシップ', ':point_right:  推薦を獲得:ショットコーラー']
        await self.safe_send(dest, random.choice(potg_strs), target)

    async def cmd_uc(self, message, dest, *cmd_args):
        '''
        U           C
        '''
        await self.safe_delete(message)
        await self.post('play', {'uri': 'https://youtu.be/ZHbzi_stmiI'}, dest.id)

    @op_only
    async def cmd_updatedb(self, message, dest, *cmd_args):
        '''
        gpmのライブラリをアップデートするコマンド

        usage {prefix}updatedb user_name
        '''
        if not cmd_args:
            await self.safe_send(dest, 'error:anger:\nusage: `{prefix}updatedb user`'.format(prefix=self.config.cmd_prefix))
            return
        await self.post('update_db', {'user': cmd_args[0]}, dest.id)

    async def cmd_web(self, message, dest, *cmd_args):
        '''
        open web ui
        '''
        await self.safe_send(dest, 'Open web player\n:point_right: https://gaiji.pro/#/play')

    @op_only
    async def cmd_token(self, message, dest, *cmd_args):
        '''
        get token

        usage {prefix}token
        '''
        await self.post('token', postback=dest.id)

    async def cmd_help(self, message, dest, *cmd_args):
        '''
        show commandlist

        usage {prefix}help
        '''
        if cmd_args:
            handler = getattr(self, f'cmd_{cmd_args[0]}', None)
            if handler:
                res_text = (f'Command: **{cmd_args[0]}**'
                            f'```{textwrap.dedent(handler.__doc__.format(prefix=self.config.cmd_prefix))}```')
                await self.safe_send(dest, res_text)
                return
            elif self.config.alias.get(cmd_args[0]):
                alias = self.config.alias.get(cmd_args[0])
                handler = getattr(self, f'cmd_{alias}', None)
                res_text = (f'Command: **{cmd_args[0]}**'
                            f'```{textwrap.dedent(handler.__doc__.format(prefix=self.config.cmd_prefix))}```')
                await self.safe_send(dest, res_text)
                return

        await self.gen_command_list()
        print_text = 'available commands\nmore info `.help [command]` ```'
        for cmd in self.commandlist:
            print_text += f'{cmd}, '
        print_text += '```'
        await self.safe_send(dest, print_text)

    @op_only
    async def cmd_test(self, message, dest, *cmd_args):
        '''
        何でも屋
        '''
        await self.post('play', {'playlist': 'Pastel*Palettes'}, dest.id)

    ##########################

    async def on_message(self, message):
        if message.author.bot:
            return
        # if message.channel.id != self.config.text_channel_id:
        #     return

        if not message.content[:len(self.config.cmd_prefix)] == self.config.cmd_prefix:
            return

        if message.author.id in self.config.blacklist:
            logging.error(f'you are in command blacklist! {message.author}:/')
            await self.safe_send(message.channel, ('you are in command blacklist! :/\n'
                                                    'if you want to control, please contact admin of this bot'), message.author)
            return

        message_content = message.content[len(self.config.cmd_prefix):].strip()
        command, *args = message_content.split(' ')
        command = command.lower()

        handler = getattr(self, f'cmd_{command}', None)

        if not handler:
            alias = self.config.alias.get(command)
            if alias:
                handler = getattr(self, f'cmd_{alias}', None)

        if handler:
            await handler(message, message.channel, *args)
        else:
            await self.safe_send(message.channel, 'いやいやいやいや\nそんな⌘ないけどガイジですか??????????', message.author)

        if message.channel.id != self.config.text_channel_id:
            await self.safe_delete(message)
