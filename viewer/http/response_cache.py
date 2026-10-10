"""Byte-bounded LRU of encoded API responses.

Trace indexes are immutable once loaded, so a successful GET response is a pure function
of its path and query parameters; repeated requests can be answered without recomputing.
"""

import collections
import threading


class ResponseCache:
    def __init__(self, budget):
        self.budget = budget
        self.size = 0
        self.entries = collections.OrderedDict()
        self.lock = threading.Lock()

    def get(self, key):
        with self.lock:
            body = self.entries.get(key)
            if body is not None:
                self.entries.move_to_end(key)
            return body

    def put(self, key, body):
        if len(body) > self.budget // 4:  # one huge response must not flush the cache
            return
        with self.lock:
            if key not in self.entries:
                self.entries[key] = body
                self.size += len(body)
                while self.size > self.budget:
                    _, evicted = self.entries.popitem(last=False)
                    self.size -= len(evicted)
