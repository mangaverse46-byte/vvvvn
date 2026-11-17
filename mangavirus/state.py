import secrets
from collections import OrderedDict

class StateStore:
    """Small bounded in-memory cache for Telegram callback payloads."""
    def __init__(self, max_items=3000):
        self.items = OrderedDict()
        self.max_items = max_items

    def put(self, value):
        token = secrets.token_urlsafe(6).replace("-", "a").replace("_", "b")[:10]
        self.items[token] = value
        self.items.move_to_end(token)
        while len(self.items) > self.max_items:
            self.items.popitem(last=False)
        return token

    def get(self, token, default=None):
        value = self.items.get(token, default)
        if token in self.items:
            self.items.move_to_end(token)
        return value
