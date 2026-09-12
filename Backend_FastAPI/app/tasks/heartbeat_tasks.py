"""Liveness heartbeat for the Celery pair (beat + worker).

WHY THIS EXISTS
---------------
``lead_watchdog_tasks`` is scheduled by beat and executed by the worker, so it
shares the failure domain of everything it backstops: when Celery is down, the
watchdog is down with it and only reports the backlog AFTER recovery. Detecting
"Celery is dead right now" therefore has to be done by something that is NOT
Celery.

This module writes the inside half of that: a timestamp that only exists if
BOTH halves of Celery are working.

* Beat must be alive to SEND the task — a dead beat stops scheduling and the
  timestamp stops advancing.
* The worker must be alive to EXECUTE it — a dead worker leaves the message
  sitting in the broker and the timestamp stops advancing just the same.

One value, two proofs. The outside half — noticing that the value stopped
advancing — is ``scripts/celery-heartbeat-monitor.sh``, run by host cron, plus
an external dead-man check that fires when the host itself goes silent.

CONTRACT WITH THE READER
------------------------
The stored value is a BARE DECIMAL epoch in seconds, nothing else: no JSON, no
prefix. The reader is a shell script on a VPS that does not have ``jq``
installed, so anything richer than an integer would have to be parsed by hand
and would fail open on the first format change.

THE TIMESTAMP IS EXECUTION TIME, NOT SCHEDULE TIME
--------------------------------------------------
``_now_epoch()`` is read INSIDE the task body, on the worker, at the moment the
work happens. There is deliberately no ``now``/``scheduled_at`` parameter
anywhere in this module: a value handed in by the caller could have been
produced by beat at publish time, and a beat-produced timestamp proves only that
beat is alive. The whole point of the signal is that it cannot be produced
without the worker.

TTL
---
The key carries ``EX 1200``, which is deliberately LONGER than the monitor's
staleness threshold (900s). That ordering matters:

* 0-900s   -> fresh, monitor pings success
* 900-1200 -> present but stale, monitor pings /fail (explicit "I looked and it
              is old")
* >1200s   -> key gone, monitor pings /fail (missing)

If the TTL were shorter than the threshold the "stale" branch would be
unreachable dead code, and a silent worker would only ever look like an absent
key. If there were no TTL at all, a stopped heartbeat would leave its last value
sitting in Redis forever — correct today because the monitor compares
timestamps, and a trap the day anything downstream treats "key exists" as "alive".
"""
import logging
import time

from redis.exceptions import RedisError

from ..celery_app import celery_app
from ..utils.redis_lock import get_redis_client
from .utils import run_async_task

log = logging.getLogger(__name__)

TASK_NAME = "celery_heartbeat_task"

# Redis DB 1 (settings.REDIS_URL). Sharing the app's cache DB on purpose: it is
# the DB that both the API process and the Celery workers already talk to, so a
# heartbeat landing there also proves the connection the rest of the app uses is
# healthy. The broker DB (2) would NOT prove that — beat can publish to a broker
# the worker can no longer read from.
HEARTBEAT_KEY = "celery:heartbeat"

# Beat interval. Kept here rather than only in celery_app.py so the monitor's
# thresholds can be checked against it; a test pins the two together.
HEARTBEAT_INTERVAL_SECONDS = 300

# See module docstring: must stay ABOVE the monitor's staleness threshold.
HEARTBEAT_TTL_SECONDS = 1200

# A heartbeat below this is not "old", it is garbage (truncated write, an
# uninitialised 0, a counter mistaken for a clock). The monitor applies the same
# floor; anything under it is treated as malformed rather than merely stale.
MIN_PLAUSIBLE_EPOCH = 1_600_000_000  # 2020-09-13

TASK_TIME_LIMIT_SECONDS = 60
TASK_SOFT_TIME_LIMIT_SECONDS = 45
# Shorter than the beat interval, so a transient Redis blip is retried and
# settled BEFORE the next scheduled heartbeat rather than piling up behind it.
RETRY_DELAY_SECONDS = 30
MAX_RETRIES = 3


def _now_epoch() -> float:
    """The one and only clock read. Tests patch this; production never passes one in."""
    return time.time()


def serialize_epoch(epoch: float) -> str:
    """Bare decimal seconds — the exact shape the shell monitor parses."""
    return str(int(epoch))


async def write_heartbeat() -> dict:
    """Stamp "a Celery worker was alive at T" into Redis.

    Raises on any Redis failure. That is the contract, not an oversight: if this
    swallowed the error and returned a success dict, the task would be marked
    SUCCEEDED while the value silently went stale, and the monitor would start
    alerting about a Celery outage that is really a Redis outage — or, worse,
    would keep reading a value nobody is refreshing. An exception here becomes a
    Celery retry and then a visible task failure.
    """
    redis = get_redis_client()
    epoch = _now_epoch()
    value = serialize_epoch(epoch)
    await redis.set(HEARTBEAT_KEY, value, ex=HEARTBEAT_TTL_SECONDS)
    return {
        "status": "ok",
        "key": HEARTBEAT_KEY,
        "epoch": int(epoch),
        "ttl": HEARTBEAT_TTL_SECONDS,
    }


@celery_app.task(
    name=TASK_NAME,
    bind=True,
    autoretry_for=(Exception,),
    max_retries=MAX_RETRIES,
    default_retry_delay=RETRY_DELAY_SECONDS,
    time_limit=TASK_TIME_LIMIT_SECONDS,
    soft_time_limit=TASK_SOFT_TIME_LIMIT_SECONDS,
)
def celery_heartbeat_task(self):
    """Celery Beat task (every 5 minutes) — thin wrapper only.

    No arguments, by design. An argument is a place where a schedule-time value
    could enter, and a schedule-time value proves the wrong thing (see module
    docstring).
    """
    task_log = logging.getLogger(TASK_NAME)

    async def _run():
        return await write_heartbeat()

    return run_async_task(_run, TASK_NAME, task_log)


# Re-exported so the retry contract can be asserted without reaching into
# Celery's decorator internals from a test.
RETRYABLE_ERROR = RedisError
