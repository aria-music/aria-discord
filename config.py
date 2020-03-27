import json
import logging


class Config:
    def __init__(self, config_file, alias_file, blacklist, op):
        self.config_file = config_file
        try:
            with open(config_file, 'r') as f:
                conf = json.load(f)
        except FileNotFoundError:
            logging.error('fatal error: config file does not exist')
            exit(1)

        self.parse_general_config(conf)

        try:
            with open(alias_file, 'r') as f:
                self.alias = json.load(f)
        except FileNotFoundError:
            logging.error('alias file does not exist')
            self.alias = {}

        try:
            with open(blacklist, 'r') as f:
                self.blacklist = json.load(f).get('user_id')
        except FileNotFoundError:
            logging.error('blacklist file does not exist')
            self.blacklist = []

        try:
            with open(op, 'r') as f:
                self.op = json.load(f).get('user_id')
        except FileNotFoundError:
            logging.error('ops file does not exist')
            self.op = []

    def parse_general_config(self, conf):
        self.token = conf.get('token')
        self.aria_token = conf.get('aria_token')
        self.stream_endpoint = conf.get('stream_endpoint')
        self.cmd_endpoint = conf.get('cmd_endpoint')
        self.voice_channel_id = int(conf.get('voice_channel_id'))
        self.text_channel_id = int(conf.get('text_channel_id'))
        if not self.token or not self.voice_channel_id or not self.text_channel_id:
            logging.error('fatal error: token or channel_id is None')
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
