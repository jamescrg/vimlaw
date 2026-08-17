"""Cross-process status store for background AI chat runs.

Every chat surface (case Analysis, intake chat, agenda chat) runs its
model call on a daemon thread inside the web worker and reports progress
under ``ai_status_<conversation_id>``, polled by the shared case:ai-status
view. The store must be visible across processes: prod runs several
gunicorn workers, and a poll usually lands in a different worker than the
one that owns the run thread. The per-process LocMem default gave each
worker a private view, so most first polls found nothing and fabricated
"the server restarted mid-run" replies (2026-08-17).

Liveness is TTL-based. In-flight writes carry a short timeout and the run
thread keeps a heartbeat that re-touches the entry while its process is
alive. If the process dies mid-run (deploy, reload, crash), the heartbeat
stops, the entry expires, and the poller reports the interruption — with
at most RUNNING_TTL of lag. Terminal payloads (complete/error) get a
longer TTL so the poller can collect them after the heartbeat has
stopped.
"""

import logging

# Bound at import on purpose: chat tests monkeypatch threading.Thread with
# an inline runner to execute the worker synchronously; the heartbeat must
# stay a real thread or that patch turns its wait-loop into a hang.
from threading import Event, Thread

from django.core.cache import caches
from django.utils.connection import ConnectionProxy

logger = logging.getLogger(__name__)

# Late-binding proxy (like django.core.cache.cache is for "default") so
# settings overrides in tests reach us.
status_cache = ConnectionProxy(caches, "ai_status")

# In-flight entries only need to outlive a few missed heartbeats; the TTL
# is also the worst-case lag between a dead process and the poller's
# "interrupted" reply.
RUNNING_TTL = 180
HEARTBEAT_SECONDS = 30
# complete/error payloads have no heartbeat behind them; give the poller
# ample time to come collect the response.
FINAL_TTL = 600


def status_key(conversation_id):
    return f"ai_status_{conversation_id}"


class RunHeartbeat:
    """Keeps a run's status entry alive while the run thread's process is.

    Start it at the top of a run thread and stop() it in a finally: the
    beat thread is a daemon, so a worker restart kills it with the run
    thread and the status entry is left to expire.
    """

    def __init__(self, conversation_id):
        self._key = status_key(conversation_id)
        self._stop = Event()

    def start(self):
        Thread(target=self._run, daemon=True).start()
        return self

    def stop(self):
        self._stop.set()

    def _run(self):
        from django.db import connections

        try:
            while not self._stop.wait(HEARTBEAT_SECONDS):
                try:
                    status_cache.touch(self._key, RUNNING_TTL)
                except Exception:
                    # A transient store hiccup must not kill the beat: the
                    # entry would expire and a live run would be reported
                    # as interrupted.
                    logger.warning("Status heartbeat write failed for %s", self._key)
        finally:
            connections.close_all()
