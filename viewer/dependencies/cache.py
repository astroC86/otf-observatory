"""Bounded, serialized dependency-view response caching."""

import collections
import functools
import pathlib
import threading

_CACHE = collections.OrderedDict()
_CACHE_LOCK = threading.RLock()


def _cached(function):
    """Keep four bounded responses, and avoid simultaneous expensive rescans."""

    @functools.wraps(function)
    def wrapper(trace, q):
        stat = pathlib.Path(trace.path).stat()
        key = (
            function.__name__,
            trace.path,
            stat.st_mtime_ns,
            tuple(sorted((str(k), str(v)) for k, v in q.items())),
        )
        with _CACHE_LOCK:
            if key in _CACHE:
                _CACHE.move_to_end(key)
                return _CACHE[key]
            value = function(trace, q)
            _CACHE[key] = value
            while len(_CACHE) > 4:
                _CACHE.popitem(last=False)
            return value

    return wrapper
