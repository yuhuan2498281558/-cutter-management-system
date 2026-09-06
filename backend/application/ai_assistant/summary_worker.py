"""Bounded, best-effort summaries outside the HTTP/SSE completion path.

Only derived summaries run here; authoritative message writes stay in the
request transaction. Revision/generation checks in MemoryService protect reset
and concurrent requests. Losing an in-process job on restart loses no history.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from django.db import close_old_connections

logger = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ai-summary")
_lock = Lock()
_pending = set()
_MAX_PENDING = 8


def schedule_summary(key, callback):
    with _lock:
        if key in _pending or len(_pending) >= _MAX_PENDING:
            return False
        _pending.add(key)

    def run():
        try:
            close_old_connections()
            callback()
        except Exception:
            logger.exception("AI background summary failed")
        finally:
            close_old_connections()
            with _lock:
                _pending.discard(key)

    try:
        _executor.submit(run)
    except Exception:
        with _lock:
            _pending.discard(key)
        logger.exception("AI background summary could not be scheduled")
        return False
    return True
