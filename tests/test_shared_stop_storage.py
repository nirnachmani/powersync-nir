"""Focused behavior tests for pending-stop write-ahead storage."""
import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / 'custom_components/power_sync/automations/shared_stop_storage.py'


def module():
    assert PATH.exists(), 'pending-stop storage helper is missing'
    spec = importlib.util.spec_from_file_location('shared_stop_storage_test', PATH)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class Store:
    def __init__(self, data=None):
        self._data = data if data is not None else {'automations': []}
        self.saved = None

    async def async_save(self):
        self.saved = json.loads(json.dumps(self._data, allow_nan=False))


def record():
    return {'generation': 'episode-1', 'binding_id': 'binding-1',
            'profile_id': 'car-a', 'owner_mode': 'smart_schedule',
            'session_id': 'session-1', 'first_attempt_at': '2026-11-05T00:00:00+00:00',
            'attempt_count': 1, 'last_status': 'pending',
            'last_attempt_at': '2026-11-05T00:00:00+00:00',
            'parameters': {'charger_switch_entity': 'switch.ev', 'charger_power_entity': 'sensor.ev'},
            'alerted': False}


def test_write_ahead_roundtrip():
    m = module()
    async def run():
        store = Store()
        saved = await m.upsert_pending_stop(store, 'generic_ev', record(), expected_generation=None, expected_revision=None)
        assert saved['revision'] == 1
        restored = Store(json.loads(json.dumps(store.saved)))
        assert await m.load_pending_stop(restored, 'generic_ev') == saved
    asyncio.run(run())


def test_cas_revision_generation_and_immutable_identity():
    m = module()
    async def run():
        store = Store()
        first = await m.upsert_pending_stop(store, 'generic_ev', record(), expected_generation=None, expected_revision=None)
        changed = dict(first, attempt_count=2, last_status='failed', last_attempt_at='2026-11-05T00:00:30Z', alerted=True)
        second = await m.upsert_pending_stop(store, 'generic_ev', changed, expected_generation='episode-1', expected_revision=1)
        assert second['revision'] == 2
        for gen, rev in [('episode-1', 1), ('older', 2), (None, None)]:
            with pytest.raises(m.PendingStopConflict):
                await m.upsert_pending_stop(store, 'generic_ev', changed, expected_generation=gen, expected_revision=rev)
        with pytest.raises(m.PendingStopConflict):
            await m.delete_pending_stop(store, 'generic_ev', expected_generation='episode-1', expected_revision=1)
        with pytest.raises(m.PendingStopConflict):
            await m.upsert_pending_stop(store, 'generic_ev', dict(second, session_id='new'), expected_generation='episode-1', expected_revision=2)
        assert await m.load_pending_stop(store, 'generic_ev') == second
        await m.delete_pending_stop(store, 'generic_ev', expected_generation='episode-1', expected_revision=2)
        assert await m.load_pending_stop(store, 'generic_ev') is None
        newer = dict(record(), generation='episode-2')
        await m.upsert_pending_stop(store, 'generic_ev', newer, expected_generation=None, expected_revision=None)
        with pytest.raises(m.PendingStopConflict):
            await m.delete_pending_stop(store, 'generic_ev', expected_generation='episode-1', expected_revision=1)
        assert (await m.load_pending_stop(store, 'generic_ev'))['generation'] == 'episode-2'
    asyncio.run(run())


def test_concurrent_writers_same_revision_only_one_wins():
    m = module()
    class SlowStore(Store):
        async def async_save(self):
            await asyncio.sleep(0.01)
            await super().async_save()
    async def run():
        store = SlowStore()
        first = await m.upsert_pending_stop(store, 'generic_ev', record(), expected_generation=None, expected_revision=None)
        async def update(status):
            return await m.upsert_pending_stop(store, 'generic_ev', dict(first, last_status=status), expected_generation='episode-1', expected_revision=1)
        results = await asyncio.gather(update('a'), update('b'), return_exceptions=True)
        assert sum(isinstance(x, m.PendingStopConflict) for x in results) == 1
        assert (await m.load_pending_stop(store, 'generic_ev'))['revision'] == 2
    asyncio.run(run())


@pytest.mark.parametrize('bad', [None, [], {'generic_ev': {}}, {'unknown': {}}])
def test_corrupt_namespace_fences_all_operations(bad):
    m = module()
    async def run():
        store = Store({m.STORAGE_KEY: bad})
        with pytest.raises(m.MalformedPendingStop):
            await m.load_pending_stop(store, 'generic_ev')
        with pytest.raises(m.MalformedPendingStop):
            await m.upsert_pending_stop(store, 'generic_ev', record(), expected_generation=None, expected_revision=None)
        with pytest.raises(m.MalformedPendingStop):
            await m.delete_pending_stop(store, 'generic_ev', expected_generation='episode-1', expected_revision=1)
    asyncio.run(run())


@pytest.mark.parametrize('change', [
    {'first_attempt_at': '2026-11-05T00:00:00'},
    {'last_attempt_at': '2026-11-04T00:00:00Z'},
    {'attempt_count': True}, {'alerted': 'false'}, {'generation': ''},
    {'parameters': {'callback': 'forbidden'}},
    {'parameters': {'charger_power_entity': ['nested']}},
    {'parameters': {'charger_power_entity': float('nan')}},
    {'unknown': 'field'},
])
def test_reject_invalid_input_without_save(change):
    m = module()
    async def run():
        store = Store()
        with pytest.raises(m.MalformedPendingStop):
            await m.upsert_pending_stop(store, 'generic_ev', dict(record(), **change), expected_generation=None, expected_revision=None)
        assert store.saved is None
        assert m.STORAGE_KEY not in store._data
    asyncio.run(run())


def test_save_failure_rolls_back_and_fences_until_reloaded():
    m = module()
    class FailingStore(Store):
        async def async_save(self):
            self._data['unrelated'] = 'preserved'
            raise OSError('uncertain write')
    async def run():
        store = FailingStore({'automations': []})
        with pytest.raises(OSError):
            await m.upsert_pending_stop(store, 'generic_ev', record(), expected_generation=None, expected_revision=None)
        assert m.STORAGE_KEY not in store._data
        assert store._data['unrelated'] == 'preserved'
        with pytest.raises(m.PendingStopError):
            await m.load_pending_stop(store, 'generic_ev')
        assert await m.load_pending_stop(Store({'automations': []}), 'generic_ev') is None
    asyncio.run(run())


def test_failed_update_and_delete_restore_old_namespace():
    m = module()
    class ToggleStore(Store):
        fail = False
        async def async_save(self):
            if self.fail:
                raise OSError('failed')
            await super().async_save()
    async def run():
        store = ToggleStore()
        first = await m.upsert_pending_stop(store, 'generic_ev', record(), expected_generation=None, expected_revision=None)
        for operation in ('update', 'delete'):
            store = ToggleStore(json.loads(json.dumps(store.saved)))
            store.fail = True
            with pytest.raises(OSError):
                if operation == 'update':
                    await m.upsert_pending_stop(store, 'generic_ev', dict(first, last_status='failed'), expected_generation='episode-1', expected_revision=1)
                else:
                    await m.delete_pending_stop(store, 'generic_ev', expected_generation='episode-1', expected_revision=1)
            assert store._data[m.STORAGE_KEY]['generic_ev'] == first
            store.saved = json.loads(json.dumps(store._data))
    asyncio.run(run())


def test_cancellation_rolls_back_and_poison_fences_waiter():
    m = module()
    class BlockingStore(Store):
        async def async_save(self):
            self.started.set()
            await asyncio.Event().wait()
    async def run():
        store = BlockingStore()
        store.started = asyncio.Event()
        task = asyncio.create_task(m.upsert_pending_stop(store, 'generic_ev', record(), expected_generation=None, expected_revision=None))
        await store.started.wait()
        waiter = asyncio.create_task(m.load_pending_stop(store, 'generic_ev'))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(m.PendingStopError):
            await waiter
        assert m.STORAGE_KEY not in store._data
    asyncio.run(run())


def test_unavailable_and_bad_id_fail_closed():
    m = module()
    async def run():
        for store in (None, object(), Store([])):
            with pytest.raises(m.PendingStopError):
                await m.load_pending_stop(store, 'generic_ev')
        with pytest.raises(m.PendingStopError):
            await m.load_pending_stop(Store(), 'logical-car')
    asyncio.run(run())


def test_multiple_physical_ids_and_detached_copies():
    m = module()
    async def run():
        store = Store()
        a = await m.upsert_pending_stop(store, 'generic_ev', record(), expected_generation=None, expected_revision=None)
        b = await m.upsert_pending_stop(store, 'sigenergy_charger', dict(record(), generation='another'), expected_generation=None, expected_revision=None)
        a['parameters']['charger_power_entity'] = 'changed'
        assert (await m.load_pending_stop(store, 'generic_ev'))['parameters']['charger_power_entity'] == 'sensor.ev'
        await m.delete_pending_stop(store, 'generic_ev', expected_generation='episode-1', expected_revision=1)
        assert await m.load_pending_stop(store, 'sigenergy_charger') == b
    asyncio.run(run())


def test_corrupt_existing_record_is_not_treated_as_missing():
    m = module()
    async def run():
        stored = dict(record(), revision=1, parameters={'callback': 'x'})
        store = Store({m.STORAGE_KEY: {'sigenergy_charger': stored}})
        with pytest.raises(m.MalformedPendingStop):
            await m.load_pending_stop(store, 'generic_ev')
        with pytest.raises(m.MalformedPendingStop):
            await m.upsert_pending_stop(store, 'generic_ev', record(), expected_generation=None, expected_revision=None)
    asyncio.run(run())


def test_synchronous_save_is_rejected_and_rolled_back():
    m = module()
    class SyncStore(Store):
        def async_save(self):
            return None
    async def run():
        store = SyncStore()
        with pytest.raises(m.PendingStopError):
            await m.upsert_pending_stop(store, 'generic_ev', record(), expected_generation=None, expected_revision=None)
        assert m.STORAGE_KEY not in store._data
        with pytest.raises(m.PendingStopError):
            await m.load_pending_stop(store, 'generic_ev')
    asyncio.run(run())


def test_backward_attempt_history_cannot_overwrite_newer_record():
    m = module()
    async def run():
        store = Store()
        first = await m.upsert_pending_stop(store, 'generic_ev', record(), expected_generation=None, expected_revision=None)
        second = await m.upsert_pending_stop(store, 'generic_ev', dict(first, attempt_count=2, last_attempt_at='2026-11-05T00:00:30Z'), expected_generation='episode-1', expected_revision=1)
        for change in ({'attempt_count': 1}, {'last_attempt_at': '2026-11-05T00:00:00Z'}, {'parameters': {}}):
            with pytest.raises(m.PendingStopConflict):
                await m.upsert_pending_stop(store, 'generic_ev', dict(second, **change), expected_generation='episode-1', expected_revision=2)
        assert await m.load_pending_stop(store, 'generic_ev') == second
    asyncio.run(run())
