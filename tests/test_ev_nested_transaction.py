"""Nested EV writes must not deadlock profile edits or admit other tasks."""
import asyncio
from types import SimpleNamespace

from test_ev_vehicle_config_deletion import deletion


def test_nested_transaction_reenters_only_owning_task(deletion):
    async def scenario():
        _, _, store, _ = deletion()
        from power_sync.automations.ev_store_lock import run_ev_store_transaction
        child_started = asyncio.Event()
        events = []

        async def child():
            child_started.set()
            await run_ev_store_transaction(store, lambda: mark('child'))

        async def mark(value):
            events.append(value)

        async def outer():
            child_task = asyncio.create_task(child())
            await child_started.wait()
            await run_ev_store_transaction(store, lambda: mark('nested'))
            assert not child_task.done()
            return child_task

        child_task = await asyncio.wait_for(run_ev_store_transaction(store, outer), 2)
        await asyncio.wait_for(child_task, 2)
        assert events == ['nested', 'child']

    asyncio.run(scenario())
