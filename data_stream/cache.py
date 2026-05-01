class Cache:
    def __init__(self):
        self.cache = {}

    def remove(self, key):
        del self.cache[key]
