import json

class Config:
    def __init__(self, config_file, alias_file, blacklist):
        self.config_file = config_file
        try:
            with open(config_file, 'r') as f:
                conf = json.load(f)
        except FileNotFoundError:
            print('fatal error: config file does not exist')
            exit(1)

        self.token = conf.get('token')
        self.stream_endpoint = conf.get('stream_endpoint')
        self.cmd_endpoint = conf.get('cmd_endpoint')
        self.voice_channel_id = int(conf.get('voice_channel_id'))
        self.text_channel_id = int(conf.get('text_channel_id'))
        if not self.token or not self.voice_channel_id or not self.text_channel_id:
            print('fatal error: token or channel_id is None')
            exit(1)

        self.cmd_prefix = conf.get('command_prefix')
        if not self.cmd_prefix:
            self.cmd_prefix = '.'

        try:
            self.serch_result_count = int(conf.get('serch_result_count'))
        except TypeError:
            self.serch_result_count = 5
        if not 1 <= self.serch_result_count <=9 or None:
            self.serch_result_count = 5

        try:
            with open(alias_file, 'r') as f:
                self.alias = json.load(f)
        except FileNotFoundError:
            print('alias file does not exist')
            self.alias = {}

        try:
            with open(blacklist, 'r') as f:
                self.blacklist = json.load(f)
        except FileNotFoundError:
            print('blacklist file does not exist')
            self.blacklist = {}