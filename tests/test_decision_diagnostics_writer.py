"""Local decision log writer: filesystem and retention contracts."""
import importlib.util
import json
import asyncio
from zoneinfo import ZoneInfo
from datetime import date, datetime, timezone
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / 'custom_components/power_sync/decision_diagnostics.py'


def load_writer():
    spec = importlib.util.spec_from_file_location('decision_diagnostics_test', MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_streams_are_separate_and_retention_does_not_remove_other_files(tmp_path):
    module = load_writer()
    writer = module.DecisionFileWriter(tmp_path)
    unrelated = tmp_path / 'other-2026-01-01.jsonl'
    unrelated.write_text('keep')
    old = tmp_path / 'ev-2026-11-06.jsonl'
    old.write_text('expired')
    kept = tmp_path / 'optimizer-2026-11-07.jsonl'
    kept.write_text('retained')
    writer.append('ev', date(2026, 11, 14), {'event': 'pause', 'amps': 0})
    writer.append('optimizer', date(2026, 11, 14), {'event': 'solve'})
    writer.prune(date(2026, 11, 14))
    assert not old.exists()
    assert kept.read_text() == 'retained'
    assert unrelated.read_text() == 'keep'
    assert json.loads((tmp_path / 'ev-2026-11-14.jsonl').read_text()) == {'event': 'pause', 'amps': 0}
    assert json.loads((tmp_path / 'optimizer-2026-11-14.jsonl').read_text()) == {'event': 'solve'}


def test_async_buffer_flushes_independent_streams(tmp_path):
    module = load_writer()

    async def exercise():
        logger = module.AsyncDecisionWriter(tmp_path, capacity=16)
        logger.start()
        assert logger.emit('ev', {'event': 'pause', 'amps': 0})
        assert logger.emit('optimizer', {'event': 'solve'})
        await logger.close()
        assert logger.dropped == 0
        assert logger.errors == 0

    asyncio.run(exercise())
    assert len(list(tmp_path.glob('ev-*.jsonl'))) == 1
    assert len(list(tmp_path.glob('optimizer-*.jsonl'))) == 1


def test_overflow_and_disk_error_are_visible_and_do_not_raise(tmp_path):
    module = load_writer()

    async def exercise():
        logger = module.AsyncDecisionWriter(tmp_path, capacity=1)
        logger.start()
        assert logger.emit('ev', {'event': 'first'})
        assert not logger.emit('ev', {'event': 'lost'})
        assert logger.dropped == 1
        def fail(*args):
            raise OSError('disk full')
        logger.files.append = fail
        await logger.close()
        assert logger.errors == 1
    asyncio.run(exercise())


def test_emit_snapshots_only_allowed_fields_and_rejects_sensitive_content(tmp_path):
    module = load_writer()

    async def exercise():
        logger = module.AsyncDecisionWriter(tmp_path, capacity=4)
        logger.start()
        payload = {'event': 'pause', 'amps': 6, 'api_key': 'do-not-write'}
        assert logger.emit('ev', payload)
        payload['amps'] = 32
        await logger.close()
    asyncio.run(exercise())
    record = json.loads(next(tmp_path.glob('ev-*.jsonl')).read_text())
    assert record['amps'] == 6
    assert 'api_key' not in record


def test_rotation_uses_ha_timezone_not_host_timezone(tmp_path):
    module = load_writer()

    async def exercise():
        when = datetime(2026, 11, 14, 14, 0, tzinfo=timezone.utc)
        logger = module.AsyncDecisionWriter(tmp_path, tz=ZoneInfo('Australia/Adelaide'), clock=lambda: when)
        logger.start()
        assert logger.emit('ev', {'event': 'pause', 'amps': 6})
        await logger.close()
    asyncio.run(exercise())
    assert (tmp_path / 'ev-2026-11-15.jsonl').exists()


def test_shared_pause_event_survives_writer(tmp_path):
    module = load_writer()
    async def exercise():
        logger = module.AsyncDecisionWriter(tmp_path)
        logger.start()
        assert logger.emit('ev', {'event': 'shared_pause_requested', 'requested_amps': 0, 'owner_mode': 'solar_surplus'})
        await logger.close()
    asyncio.run(exercise())
    record = json.loads(next(tmp_path.glob('ev-*.jsonl')).read_text())
    assert record['requested_amps'] == 0
    assert record['owner_mode'] == 'solar_surplus'


def test_accepted_events_include_utc_timestamp_and_order(tmp_path):
    module = load_writer()
    async def exercise():
        when = datetime(2026, 11, 14, 14, 0, tzinfo=timezone.utc)
        logger = module.AsyncDecisionWriter(tmp_path, clock=lambda: when)
        logger.start()
        assert logger.emit('ev', {'event': 'pause', 'amps': 6})
        assert logger.emit('ev', {'event': 'pause', 'amps': 0})
        await logger.close()
    asyncio.run(exercise())
    records = [json.loads(line) for line in next(tmp_path.glob('ev-*.jsonl')).read_text().splitlines()]
    assert [record['sequence'] for record in records] == [1, 2]
    assert records[0]['timestamp_utc'] == '2026-11-14T14:00:00+00:00'
    assert records[0]['schema_version'] == 1


def test_numeric_fields_cannot_hide_secrets(tmp_path):
    module = load_writer()
    async def exercise():
        logger = module.AsyncDecisionWriter(tmp_path)
        logger.start()
        assert logger.emit('ev', {'event': 'shared_pause_requested', 'requested_amps': 'secret'})
        await logger.close()
    asyncio.run(exercise())
    text = next(tmp_path.glob('ev-*.jsonl')).read_text()
    assert 'secret' not in text


def test_battery_target_fields_survive_writer(tmp_path):
    module = load_writer()
    async def exercise():
        logger = module.AsyncDecisionWriter(tmp_path)
        logger.start()
        assert logger.emit('ev', {'event': 'battery_target_decision', 'grid_limit_kw': 12.5,
                                  'battery_target_kw': 10.0, 'planned_ev_kw': None,
                                  'requested_amps': 0, 'owner_mode': 'smart_schedule'})
        await logger.close()
    asyncio.run(exercise())
    record = json.loads(next(tmp_path.glob('ev-*.jsonl')).read_text())
    assert record['grid_limit_kw'] == 12.5 and record['battery_target_kw'] == 10.0
    assert 'planned_ev_kw' in record and record['planned_ev_kw'] is None


def test_close_is_bounded_when_io_is_stuck(tmp_path):
    module = load_writer()
    import threading
    entered, release = threading.Event(), threading.Event()
    async def exercise():
        writer = module.AsyncDecisionWriter(tmp_path, shutdown_timeout=0.05)
        def stalled(*args):
            entered.set()
            release.wait(2)
        writer.files.append = stalled
        writer.start()
        assert writer.emit('ev', {'event': 'pause', 'amps': 0})
        await asyncio.to_thread(entered.wait, 1)
        await asyncio.wait_for(writer.close(), 0.5)
        assert writer.dropped >= 1
        release.set()
    try:
        asyncio.run(exercise())
    finally:
        release.set()


def test_preliminary_optimizer_budget_and_slots_survive_writer(tmp_path):
    module = load_writer()
    async def exercise():
        writer = module.AsyncDecisionWriter(tmp_path)
        writer.start()
        assert writer.emit('optimizer', {'event': 'solar_export_budget', 'current_soc': .13,
            'trace_id': 'a' * 32,
            'future_capacity_kwh': [0.1, 2.0], 'future_solar_capacity_kwh': [0.1, 0],
            'future_grid_capacity_kwh': [0, 2.0], 'future_cost_per_kwh': [None, 0.0], 'interval_hours': 1/12,
            'import_prices': [0.1, 0.2], 'grid_charge_allowed': [False, True],
            'grid_export_limits_w': None, 'allow_grid_charge': True})
        assert writer.emit('optimizer', {'event': 'solar_export_slot', 'slot_index': 0,
            'reason': 'selected', 'selected': True, 'eligible_replenishment_kwh': 2.0,
            'replenishment_slots': [1], 'replenishment_used_kwh': [0.2]})
        await writer.close()
    asyncio.run(exercise())
    rows = [json.loads(line) for line in next(tmp_path.glob('optimizer-*.jsonl')).read_text().splitlines()]
    assert rows[0]['trace_id'] == 'a' * 32
    assert rows[0]['future_capacity_kwh'] == [0.1, 2.0]
    assert rows[0]['future_solar_capacity_kwh'] == [0.1, 0]
    assert rows[0]['future_grid_capacity_kwh'] == [0, 2.0]
    assert rows[0]['import_prices'] == [0.1, 0.2]
    assert rows[0]['grid_charge_allowed'] == [False, True]
    assert rows[0]['grid_export_limits_w'] is None and rows[0]['allow_grid_charge'] is True
    assert rows[1]['reason'] == 'selected' and rows[1]['eligible_replenishment_kwh'] == 2.0
    assert rows[1]['replenishment_slots'] == [1]
    assert rows[1]['replenishment_used_kwh'] == [0.2]


def test_start_prunes_expired_files_without_events(tmp_path):
    module = load_writer()
    from datetime import datetime, timezone
    stale = tmp_path / 'ev-2026-11-01.jsonl'
    stale.write_text('old\n')
    async def exercise():
        writer = module.AsyncDecisionWriter(tmp_path, clock=lambda: datetime(2026, 11, 14, tzinfo=timezone.utc), tz=timezone.utc)
        writer.start()
        await writer.close()
    asyncio.run(exercise())
    assert not stale.exists()


def test_failed_write_increments_dropped_counter(tmp_path):
    module = load_writer()
    async def exercise():
        writer = module.AsyncDecisionWriter(tmp_path)
        def fail(*args):
            raise OSError('disk full')
        writer.files.append = fail
        writer.start()
        assert writer.emit('ev', {'event': 'pause', 'amps': 0})
        await writer.close()
        assert writer.errors == 1
        assert writer.dropped == 1
    asyncio.run(exercise())


def test_idle_writer_prunes_after_day_changes(tmp_path):
    module = load_writer()
    from datetime import datetime, timezone
    now = [datetime(2026, 11, 9, tzinfo=timezone.utc)]
    stale = tmp_path / 'ev-2026-11-03.jsonl'
    stale.write_text('old\n')
    async def exercise():
        writer = module.AsyncDecisionWriter(tmp_path, clock=lambda: now[0], tz=timezone.utc, maintenance_interval=0.01)
        writer.start()
        await asyncio.sleep(.03)
        assert stale.exists()
        now[0] = datetime(2026, 11, 14, tzinfo=timezone.utc)
        await asyncio.sleep(.05)
        await writer.close()
    asyncio.run(exercise())
    assert not stale.exists()


def test_stop_observation_persists_unknown_and_fresh_values(tmp_path):
    module = load_writer()
    async def exercise():
        writer = module.AsyncDecisionWriter(tmp_path)
        writer.start()
        assert writer.emit('ev', {'event': 'stop_observation', 'trace_id': 'c' * 32,
                                  'charging': None, 'power_kw': None, 'charger_type': 'generic',
                                  'observation_age_seconds': None})
        assert writer.emit('ev', {'event': 'stop_observation', 'trace_id': 'c' * 32,
                                  'charging': False, 'power_kw': 0.0, 'charger_type': 'generic',
                                  'observation_age_seconds': .5})
        await writer.close()
    asyncio.run(exercise())
    rows = [json.loads(line) for line in next(tmp_path.glob('ev-*.jsonl')).read_text().splitlines()]
    assert rows[0]['charging'] is None and rows[0]['power_kw'] is None
    assert rows[1]['charging'] is False and rows[1]['power_kw'] == 0
    assert rows[1]['charger_type'] == 'generic' and rows[1]['trace_id'] == 'c' * 32


def test_price_decision_persists_missing_soc(tmp_path):
    module = load_writer()
    async def run():
        writer = module.AsyncDecisionWriter(tmp_path)
        writer.start()
        assert writer.emit('ev', {'event': 'price_level_decision', 'ev_soc': None, 'price_cents': 25,
                                  'recovery_soc': 40, 'recovery_price_cents': 30,
                                  'opportunity_price_cents': 10, 'should_charge': True,
                                  'owner_mode': 'price_level_recovery'})
        await writer.close()
    asyncio.run(run())
    row = json.loads(next(tmp_path.glob('ev-*.jsonl')).read_text())
    assert row['ev_soc'] is None and row['price_cents'] == 25
    assert row['should_charge'] and row['owner_mode'] == 'price_level_recovery'


def test_smart_schedule_decision_persists_missing_values(tmp_path):
    module = load_writer()
    async def run():
        writer = module.AsyncDecisionWriter(tmp_path)
        writer.start()
        assert writer.emit('ev', {'event': 'smart_schedule_decision', 'reported_state': 'complete',
                                  'target_soc': 80, 'price_cents': None, 'is_charging': False})
        await writer.close()
    asyncio.run(run())
    row = json.loads(next(tmp_path.glob('ev-*.jsonl')).read_text())
    assert row['reported_state'] == 'complete' and row['target_soc'] == 80
    assert row['price_cents'] is None and row['is_charging'] is False


def test_nonfinite_numbers_do_not_erase_entire_event(tmp_path):
    module = load_writer()
    async def run():
        writer = module.AsyncDecisionWriter(tmp_path)
        writer.start()
        assert writer.emit('ev', {'event': 'solar_rate_decision', 'reason': 'optimizer_zero',
                                  'battery_soc': float('nan'), 'requested_amps': 0})
        await writer.close()
        assert writer.errors == 0
    asyncio.run(run())
    row = json.loads(next(tmp_path.glob('ev-*.jsonl')).read_text())
    assert row['battery_soc'] is None and row['requested_amps'] == 0
    assert row['invalid_numeric_fields'] == ['battery_soc']


def test_nonfinite_forecast_values_are_marked_not_lost(tmp_path):
    module = load_writer()
    async def run():
        writer = module.AsyncDecisionWriter(tmp_path)
        writer.start()
        assert writer.emit('optimizer', {'event': 'solar_export_budget', 'import_prices': [0.1, float('inf')]})
        await writer.close()
        assert writer.errors == 0
    asyncio.run(run())
    row = json.loads(next(tmp_path.glob('optimizer-*.jsonl')).read_text())
    assert row['import_prices'] == [0.1, None]
    assert row['invalid_numeric_fields'] == ['import_prices[1]']


def test_write_recovery_records_diagnostic_gap(tmp_path):
    module = load_writer()
    async def run():
        writer = module.AsyncDecisionWriter(tmp_path)
        original = writer.files.append
        failures = [True]
        def intermittent(stream, day, event):
            if failures:
                failures.pop()
                raise OSError('full')
            return original(stream, day, event)
        writer.files.append = intermittent
        writer.start()
        assert writer.emit('ev', {'event': 'pause'})
        assert writer.emit('ev', {'event': 'pause'})
        await writer.close()
    asyncio.run(run())
    rows = [json.loads(line) for line in next(tmp_path.glob('ev-*.jsonl')).read_text().splitlines()]
    gap = next(r for r in rows if r['event'] == 'diagnostic_gap')
    assert gap['dropped_total'] == 1 and gap['errors_total'] == 1


def test_write_error_warns_without_logging_sensitive_exception(tmp_path, caplog):
    module = load_writer()
    async def run():
        writer = module.AsyncDecisionWriter(tmp_path)
        def fail(*args):
            raise OSError('private-data-sentinel')
        writer.files.append = fail
        writer.start()
        writer.emit('ev', {'event': 'pause'})
        await writer.close()
    asyncio.run(run())
    assert 'PowerSync decision logging' in caplog.text
    assert 'private-data-sentinel' not in caplog.text


def test_entry_lifecycle_records_in_ha_config_and_flushes(tmp_path):
    from types import SimpleNamespace
    module = load_writer()
    config = SimpleNamespace(path=lambda name: str(tmp_path / name), time_zone='Australia/Adelaide')
    hass = SimpleNamespace(config=config)
    async def run():
        writer = module.start_entry_diagnostics(hass, 'entry-1', 'test-version')
        assert writer.emit('ev', {'event': 'price_level_decision', 'price_cents': 25})
        await writer.close()
    asyncio.run(run())
    row = json.loads(next((tmp_path / 'power_sync_diagnostics').glob('ev-*.jsonl')).read_text())
    assert row['price_cents'] == 25 and row['version'] == 'test-version'
    assert row['session_id']


def test_event_name_rejects_unrecognized_or_sensitive_string(tmp_path):
    module = load_writer()

    async def exercise():
        logger = module.AsyncDecisionWriter(tmp_path)
        logger.start()
        assert not logger.emit('ev', {'event': 'secret-user-token'})
        await logger.close()
    asyncio.run(exercise())
    assert not list(tmp_path.glob('ev-*.jsonl'))
