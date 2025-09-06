import etcd3
import pickle

from config import Config

class Etcd:
    def __init__(self, host = Config.HOST, port = Config.ETCD_PORT):
        self.etcd = etcd3.client(host = host, port = port)
        print(f'[INFO]Etcd Init: host = {host} port = {port}')

    def reset(self):
        keys = Config.RESET_PREFIX
        for key in keys:
            self.etcd.delete_prefix(key)

    def get_prefix(self, prefix_key):
        # List[(value, metadata)]
        range_response = self.etcd.get_prefix(prefix_key)
        return [pickle.loads(value) if value else None
            for value, metadata in range_response]

    def get(self, key, ret_meta = False):
        value, metadata = self.etcd.get(key)
        return pickle.loads(value) if value else None

    def put(self, key, value):
        self.etcd.put(key, pickle.dumps(value))

    def delete(self, key):
        self.etcd.delete(key)