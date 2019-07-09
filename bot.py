import asyncio
import json
import re
import textwrap
import threading
import logging

import discord

from config import Config
from opus_loader import load_opus_libs
from player import play

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

        self.player_status = {
            'state': False,
            'source': None,
            'title': None,
            'album': None,
            'artist': None,
            'uri': None,
            'is_liked': False
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
            'white_check_mark': '\U00002705'
        }

    async def on_ready(self):
        logging.info('connected to discord')
        #await asyncio.wait_for(self.join_vc(), timeout=5.0)
        await self.join_vc()
        await self.post('discord ready')
        logging.info('discord vc connect')
        player = threading.Thread(target=play, args=(self.player_queue, self.voice, self.loop), daemon=True)
        response_handler = threading.Thread(target=self.handle_res, daemon=True)
        player.start()
        response_handler.start()
        logging.info('connected to vc')

    async def safe_send(self, dest, payload, user=None):
        '''
        Parameters
        ----------
        dest: discord.channel.TextChannel
        payload: str
        user: message.author.mention

        Returns
        -------
        msg
        '''
        try:
            if user:
                msg = await dest.send(f'{user}\n{payload}')
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
        self.channel = self.get_channel(self.config.voice_channel_id)
        self.voice = await self.channel.connect()

    async def exit_vc(self):
        self.player = None
        await self.voice.disconnect()

    async def post(self, op, data=None):
        '''
        post op and message
        '''
        async with lock:
            self.ctrl_queue.put_nowait((op, data))

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
        await self.change_presence(status=discord.Status.online, activity=playing_status)

    def handle_res(self):
        self.loop.create_task(self._handle_res())

    async def _handle_res(self):

        async def _wait_packet():
            '''
            50ms sleep
            '''
            await asyncio.sleep(0.05)

        while True:
            await lock.acquire()
            if self.res_queue.empty():
                lock.release()
                await asyncio.wait_for(_wait_packet(), timeout=0.5)
                continue
            else:
                res = self.res_queue.get_nowait()
                lock.release()
                response_type = res.get('type')
                if response_type == 'search':
                    await self.search(res)
                elif response_type == 'list_queue':
                    await self.set_play_queue(res)
                elif response_type == 'state':
                    await self.set_player_status(res)
                elif response_type == 'playlists':
                    await self.show_playlists(res)
                elif response_type == 'playlist':
                    await self.show_likelen(res)
                elif response_type == 'event_player_state_change':
                    await self.set_player_status(res)
                elif response_type == 'event_queue_change':
                    await self.set_play_queue(res)
                elif response_type == 'event_playlists_change':
                    pass
                elif response_type == 'event_playlist_entry_change':
                    pass
                else:
                    logging.warning('error: unexpected response type')


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
            if self.player_status['source'] == 'gpm':
                self.player_status['title'] = entry.get('entry').get('title')
                self.player_status['album'] = entry.get('entry').get('album')
                self.player_status['artist'] = entry.get('entry').get('artist')
            else:
                self.player_status['album'] = None
                self.player_status['artist'] = None
        else:
            self.player_status['source'] = None
            self.player_status['title'] = None
            self.player_status['title'] = None
            self.player_status['album'] = None
            self.player_status['artist'] = None
            self.player_status['uri'] = None

        await self.set_game_activity()

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
        dest = self.get_channel(self.config.text_channel_id)
        result = await self.parse_result(raw_result)
        if not result:
            res_text = f'Sorry\ncould not find any track'
            await self.safe_send(dest, res_text)
            return

        res_text = (f'**search result**\n'
                    f'**{len(result)}** hits')
        await self.safe_send(dest, res_text)

        res_count = self.config.serch_result_count
        total_page = -(-len(result) // res_count)
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
            for i in ['fast_forward', 'no_entry_sign', 'white_check_mark']:
               await msg.add_reaction(self.control[i])

            def check(reaction, user):
                return user != msg.author and reaction.message.id == msg.id

            next_page = False
            while True:
                try:
                    reaction, _ = await self.wait_for('reaction_add', timeout=60.0, check=check)

                    if str(reaction.emoji) == '\U000023E9':#fast_forward
                        await self.safe_delete(msg)
                        next_page = True
                        break
                    elif str(reaction.emoji) == '\U0001F6AB':#no_entry_sign
                        await self.safe_delete(msg)
                        return
                    elif str(reaction.emoji) == '\U00002705':#white_check_mark
                        await self.safe_delete(msg)
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
                gpm_info = [entry.get('entry').get(i) for i in ['title', 'album', 'artist']]
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
                gpm_info = [entry.get('entry').get(i) for i in ['title', 'album', 'artist']]
                gpm_info.insert(0, source)
                gpm_info.append(uri)
                resp.append(tuple(gpm_info))
            else:
                resp.append((source, title, None, None, uri))
        return resp

    async def show_playlists(self, res):
        _playlists = {}
        dest = self.get_channel(self.config.text_channel_id)

        for entry in res.get('data').get('playlists'):
            _playlists[entry.get('name')] = entry.get('length')

        res_text = ''
        res_text = 'playlist\n\n'
        for i in _playlists:
            res_text += f':file_folder: **{i}** has **{_playlists[i]}** tracks :musical_note:\n'
        res_text += '\nmore info use web client'

        await self.safe_send(dest, res_text)

    async def show_likelen(self, res):
        dest = self.get_channel(self.config.text_channel_id)

        lenlist = len(res.get('data').get('entries'))

        await self.safe_send(dest, f'Likes has **{lenlist}** tracks :musical_note: \nmore info use web client')

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
                                f'        {song[2]} / {song[3]} - from: gpm\n')
            else:
                numberd_list += (f'{num} **{song[1]}**\n'
                                f'        - from: {song[0]}\n')

        return numberd_list

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
            await self.post('queue', {'uri':cmd_args[0]})
        else:
            await self.post('queue', {'uri':[i for i in cmd_args]})

    async def cmd_repeat(self, message, dest, *cmd_args):
        '''
        repeat now-playing song

        usage {prefix}repeat <num>
        '''
        if not cmd_args:
            await self.post('repeat', {'uri': self.player_status.get('uri')})
            return
        try:
            count = int(cmd_args[0])
            await self.post('repeat', {'uri': self.player_status.get('uri'), 'count': count})
        except ValueError:
            await self.post('repeat', {'uri': self.player_status.get('uri')})

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
            await self.post('pause')

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
            await self.post('resume')

    async def cmd_skip(self, message, dest, *cmd_args):
        '''
        skip

        usage {prefix}skip
        '''
        if not cmd_args:
            await self.post('skip')
            return
        try:
            index = int(cmd_args[0]) - 1
            await self.post('skip_to', {'index': index, 'uri': self.play_queue.get('data').get('queue')[index].get('uri')})
        except ValueError:
            await self.post('skip')

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
            await self.post('skip_to', {'index': index, 'uri': self.play_queue.get('data').get('queue')[index].get('uri')})
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
        await self.post('queue', {'uri': cmd_args[0], 'head': True})

    async def cmd_add(self, message, dest, *cmd_args):
        '''
        store auto playlist

        usage {prefix}add URL(s)
        '''
        if not cmd_args:
            await dest.send('error:anger:\n usage `{prefix}add URL(s)`'.format(prefix=self.config.cmd_prefix))
            return
        if len(cmd_args) == 1:
            await self.post('add_to_playlist', {'name': 'Likes', 'uri':cmd_args[0]})
        else:
            for i in cmd_args:
                await self.post('add_to_playlist', {'name': 'Likes', 'uri':i})

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
            await self.post('remove', {'index': index, 'uri': self.play_queue.get('data').get('queue')[index].get('uri')})
        except ValueError:
            await self.safe_send(dest, 'error:anger:\n usage `{prefix}remove num`'.format(prefix=self.config.cmd_prefix))

    async def cmd_np(self, message, dest, *cmd_args):
        '''
        show song info

        usage {prefix}np
        '''
        try:
            await asyncio.wait_for(self.post('state'), timeout=1.0)
        except TimeoutError:
            logging.error('TimeoutError')
            return
        res_text = ''
        if self.player_status.get('state') == 'playing':
            res_text = f':arrow_forward: **{self.player_status.get("title")}\n\n**'
        else:
            res_text = f':pause_button: **{self.player_status.get("title")}\n\n**'
        if self.player_status.get('source') == 'gpm':
            res_text += (f'        album: **{self.player_status.get("album")}**\n'
                        f'        artist: **{self.player_status.get("artist")}**\n'
                        '        from: **gpm**')
        else:
            res_text += f'        from: **{self.player_status.get("source")}**'
        await self.safe_send(dest, res_text)
    """
    async def cmd_like(self, message, dest, *cmd_args):
        '''
        save current track to playlist [Likes]

        usage {prefix}like
        '''
        await self.post('like', {'uri': self.player_status.get('uri')})
    """
    async def cmd_likes(self, message, dest, *cmd_args):
        '''
        show how many songs in playlist [Likes]

        usage {prefix}likes
        '''
        await self.post('playlist', {'name': 'Likes'})

    async def cmd_playlists(self, message, dest, *cmd_args):
        '''
        show playlists name

        usage {prefix}playlists
        '''
        await self.post('playlists')

    async def cmd_clear(self, message, dest, *cmd_args):
        '''
        clear queue

        usage {prefix}clear
        '''
        await self.post('clear_queue')

    async def cmd_shuffle(self, message, dest, *cmd_args):
        '''
        shuffle queue

        usage {prefix}shuffle
        '''
        await self.post('shuffle')

    async def cmd_purge(self, message, dest, *cmd_args):
        '''
        remove from auto playlist

        usage {prefix}purge URLs
        '''
        if not cmd_args:
            if self.player_status.get('is_liked'):
                await self.post('remove_from_playlist', {'name':'Likes', 'uri': self.player_status.get('uri')})
            else:
                await self.safe_send(dest, 'error:anger:\nThis track is not in Likes')
            return
        for url in cmd_args:
            await self.post('remove_from_playlist', {'name':'Likes', 'uri': url})

    async def cmd_save(self, message, dest, *cmd_args):
        '''
        save song into auto playlist

        usage {prefix}save
        '''
        await self.post('add_to_playlist', {'name': 'Likes', 'uri': self.player_status.get('uri')})

    async def cmd_search(self, message, dest, *cmd_args):
        '''
        search song in youtube and gpm

        usage {prefix}search keyword
        '''
        if not cmd_args:
            await dest.send('error:anger:\nusage `{prefix}search keyword`'.format(prefix=self.config.cmd_prefix))
            return
        else:
            query = ' '.join(cmd_args)
            await self.post('search', {'query': query})

    async def cmd_gsearch(self, message, dest, *cmd_args):
        '''
        search song in gpm

        usage {prefix}gsearch keyword
        '''
        if not cmd_args:
            await dest.send('error:anger:\nusage `{prefix}gsearch keyword`'.format(prefix=self.config.cmd_prefix))
            return
        else:
            query = ' '.join(cmd_args)
            await self.post('search', {'query': query, 'provider': 'gpm'})

    async def cmd_ysearch(self, message, dest, *cmd_args):
        '''
        search song in youtube

        usage {prefix}ysearch keyword
        '''
        if not cmd_args:
            await dest.send('error:anger:\nusage `{prefix}ysearch keyword`'.format(prefix=self.config.cmd_prefix))
            return
        else:
            query = ' '.join(cmd_args)
            await self.post('search', {'query': query, 'provider': 'youtube'})

    async def cmd_join(self, message, dest, *cmd_args):
        '''
        [operator only]join VC

        usage {prefix}join
        '''
        if self.voice.is_connected():
            await dest.send(f'{self.user} is already in VC')
            return
        await self.join_vc()

    async def cmd_kick(self, message, dest, *cmd_args):
        '''
        [operator only]kick bot from VC

        usage {prefix}kick
        '''
        if not self.voice.is_connected():
            await dest.send(f'{self.user} is not in VC')
            return
        await self.exit_vc()

    async def cmd_logout(self, message, dest, *cmd_args):
        '''
        [operator only]

        usage {prefix}logout
        '''
        await self.logout()
        exit(1)

    async def cmd_reconnect(self, message, dest, *cmd_args):
        '''
        reconnect VC

        usage {prefix}reconnect
        '''
        try:
            await asyncio.wait_for(self.exit_vc(), timeout=1.0)
        except TimeoutError:
            logging.error('TimeoutError')
            return
        await self.join_vc()

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
        fuck_str = ':regional_indicator_f: :regional_indicator_u: :regional_indicator_c: :regional_indicator_k: :regional_indicator_y: :regional_indicator_o: :regional_indicator_u: '
        await self.safe_send(dest, fuck_str, message.author.mention)

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

    ##########################

    async def on_message(self, message):
        if message.author.bot:
            return
        if message.channel.id != self.config.text_channel_id:
            return

        if message.author.id in self.config.blacklist:
            logging.error(f'you are in command blacklist! {message.author}:/')
            await self.safe_send(message.channel, (f'{message.author.mention}you are in command blacklist! :/\n'
                                                    'if you want to control, please contact admin of this bot'))
            return

        if not message.content[:len(self.config.cmd_prefix)] == self.config.cmd_prefix:
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
