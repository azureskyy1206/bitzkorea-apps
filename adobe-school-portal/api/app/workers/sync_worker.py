"""Adobe UMAPI sync_queue 워커 — pending 작업 폴링·처리."""

from __future__ import annotations

import asyncio
import signal

import structlog
from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.models import SyncQueue, SyncState
from app.services.sync_enqueue import _adobe_configured
from app.services.sync_processor import process_sync_job

log = structlog.get_logger()

_BATCH_SIZE = 10
_IDLE_SECONDS = 5.0
_WAKE_POLL_SECONDS = 1.0


async def _process_batch() -> int:
    if not _adobe_configured():
        return 0

    processed = 0
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SyncQueue)
            .where(SyncQueue.state == SyncState.pending)
            .order_by(SyncQueue.id.asc())
            .limit(_BATCH_SIZE)
            .with_for_update(skip_locked=True)
        )
        jobs = list(result.scalars().all())
        if not jobs:
            return 0

        for job in jobs:
            job.state = SyncState.processing
        await session.commit()

        for job in jobs:
            async with AsyncSessionLocal() as job_session:
                j = await job_session.get(SyncQueue, job.id)
                if j is None or j.state != SyncState.processing:
                    continue
                try:
                    await process_sync_job(job_session, j)
                    await job_session.commit()
                    processed += 1
                except Exception:
                    await job_session.commit()
    return processed


async def _run_loop(stop: asyncio.Event) -> None:
    if not _adobe_configured():
        log.warning(
            "sync_worker_adobe_not_configured",
            note="ADOBE_ORG_ID, CLIENT_ID, CLIENT_SECRET 설정 후 재시작",
        )

    redis = None
    pubsub = None
    try:
        from app.services.redis_client import get_redis

        redis = get_redis()
        pubsub = redis.pubsub()
        await pubsub.subscribe("adobe_sync:wake")
    except Exception as e:
        log.warning("sync_worker_redis_subscribe_failed", error=str(e))

    log.info("sync_worker_started")
    while not stop.is_set():
        try:
            n = await _process_batch()
            if n > 0:
                continue
        except Exception as e:
            log.exception("sync_worker_batch_error", error=str(e))

        if pubsub is not None:
            try:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=_WAKE_POLL_SECONDS)
                if msg:
                    continue
            except Exception:
                pass

        try:
            await asyncio.wait_for(stop.wait(), timeout=_IDLE_SECONDS)
        except asyncio.TimeoutError:
            pass

    if pubsub is not None:
        await pubsub.unsubscribe("adobe_sync:wake")
        await pubsub.aclose()
    if redis is not None:
        await redis.aclose()
    log.info("sync_worker_stopped")


def main() -> None:
    stop = asyncio.Event()

    def _handle_sig(*_args: object) -> None:
        stop.set()

    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)
    asyncio.run(_run_loop(stop))


if __name__ == "__main__":
    main()
