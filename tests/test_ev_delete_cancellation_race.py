"""Cancellation must not release deletion's lock while its save is in flight."""
import asyncio
from types import SimpleNamespace

from test_ev_vehicle_config_deletion import deletion


def test_cancelled_delete_keeps_transaction_lock_until_save_finishes(deletion):
    async def scenario():
        view, profiles, store, executor = deletion('byd_device')
        entered, release = asyncio.Event(), asyncio.Event()
        original = store.async_save

        async def delayed(data):
            entered.set()
            await release.wait()
            await original(data)

        store.async_save = delayed
        task = asyncio.create_task(view.delete(SimpleNamespace(query={'vehicle_id': 'byd_device'})))
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        from power_sync.automations.ev_store_lock import ev_store_lock
        lock = ev_store_lock(store)
        assert lock.locked(), 'cancel released lock during shielded durable save'
        release.set()
        async with lock:
            pass
        assert 'byd_device' not in store.data['auto_schedule_settings']
        assert 'byd_device' not in [c['vehicle_id'] for c in profiles._data['vehicle_charging_configs']]
    asyncio.run(scenario())
