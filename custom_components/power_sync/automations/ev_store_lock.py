"""Serialize EV profile deletion with EV persistence transactions."""

import asyncio


async def run_ev_store_transaction(store, operation):
    """Finish a started transaction even when its caller is cancelled."""
    # A transaction may invoke another EV persistence operation (for example,
    # profile editing regenerates a plan which caches SoC). Re-enter only from
    # the actual owning task, never from a spawned task inheriting its context.
    if vars(store).get("_power_sync_ev_owner") is asyncio.current_task():
        return await operation()

    async def transaction():
        async with ev_store_lock(store):
            store._power_sync_ev_owner = asyncio.current_task()
            try:
                return await operation()
            finally:
                store._power_sync_ev_owner = None

    tasks = vars(store).setdefault("_power_sync_ev_transactions", set())
    task = asyncio.create_task(transaction())
    tasks.add(task)

    def finished(done):
        tasks.discard(done)
        if not done.cancelled():
            done.exception()

    task.add_done_callback(finished)
    return await asyncio.shield(task)


async def cancellation_safe_save(awaitable):
    """Keep the caller's lock until an in-flight whole-store save finishes.

    HA saves can continue in an executor after their awaiting task is cancelled.
    Shield the save itself and defer cancellation until it has completed.
    """
    task = asyncio.ensure_future(awaitable)
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            break
    if cancelled:
        if not task.cancelled():
            task.exception()  # Retrieve any write failure before propagating cancellation.
        raise asyncio.CancelledError
    return task.result()


def ev_store_lock(store):
    """Return the per-entry settings-store lock, shared with runtime storage."""
    lock = vars(store).get("_power_sync_ev_lock")
    if lock is None:
        lock = store._power_sync_ev_lock = asyncio.Lock()
    return lock
