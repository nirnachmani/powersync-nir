"""Local decision-log file rotation primitives.

Call only in a worker thread. This module does not attach to HA or controls.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import asyncio
import hashlib
import json
import logging
import math
import os
import queue
import threading
from concurrent.futures import Future
import time
from pathlib import Path
import re
from uuid import uuid4
from zoneinfo import ZoneInfo

_LOGGER = logging.getLogger(__name__)
_NAME = re.compile(r"^(ev|optimizer)-(\d{4}-\d{2}-\d{2})\.jsonl$")
_NAS_MOUNT = Path('/share/NAS_Backup')

# One daemon per integration module: a hung NFS operation cannot occupy HA's
# shared executor or create an unbounded thread per retry/reload.
_disk_jobs = queue.Queue(maxsize=1)
_disk_start_lock = threading.Lock()
_disk_thread = None


def _disk_worker():
    while True:
        future, func, args = _disk_jobs.get()
        try:
            if future.set_running_or_notify_cancel():
                try:
                    future.set_result(func(*args))
                except BaseException as exc:
                    future.set_exception(exc)
        finally:
            _disk_jobs.task_done()


async def _disk_call(func, *args):
    global _disk_thread
    with _disk_start_lock:
        if _disk_thread is None or not _disk_thread.is_alive():
            _disk_thread = threading.Thread(target=_disk_worker, name='powersync-diagnostics-disk', daemon=True)
            _disk_thread.start()
    future = Future()
    try:
        _disk_jobs.put_nowait((future, func, args))
    except queue.Full as exc:
        raise OSError('decision logging disk worker is busy') from exc
    # Cancellation cannot stop a kernel NFS call; the sole daemon remains
    # isolated until it returns. Queued, cancelled jobs are skipped.
    return await asyncio.wait_for(asyncio.wrap_future(future), timeout=5.0)


class DecisionFileWriter:
    """Append JSON Lines and remove only expired files owned by the logger."""

    def __init__(self, directory: Path, *, required_mount: Path | None = None):
        self.directory = Path(directory)
        self.required_mount = required_mount

    def _check_mount(self) -> None:
        if self.required_mount is not None and not os.path.ismount(self.required_mount):
            raise OSError('decision diagnostics NAS share is not mounted')

    def append(self, stream: str, day: date, event: dict) -> None:
        if stream not in {"ev", "optimizer"}:
            raise ValueError("unknown decision stream")
        self._check_mount()
        data = json.dumps(event, separators=(",", ":"), allow_nan=False)
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / f"{stream}-{day.isoformat()}.jsonl").open("a", encoding="utf-8") as output:
            output.write(data + "\n")

    def prune(self, today: date) -> None:
        self._check_mount()
        if not self.directory.exists():
            return
        cutoff = today - timedelta(days=7)
        for path in self.directory.iterdir():
            match = _NAME.fullmatch(path.name)
            if not match or path.is_symlink() or not path.is_file():
                continue
            try:
                file_date = date.fromisoformat(match.group(2))
            except ValueError:
                continue
            if file_date < cutoff:
                path.unlink()


def start_entry_diagnostics(hass, entry_id, version, *, enabled=True):
    """Start the entry-local writer using Home Assistant's configured timezone."""
    if not enabled:
        return None
    writer = AsyncDecisionWriter(_NAS_MOUNT / 'power_sync_diagnostics',
                                 tz=ZoneInfo(hass.config.time_zone), version=version,
                                 required_mount=_NAS_MOUNT)
    writer.entry_alias = hashlib.sha256(entry_id.encode()).hexdigest()[:12]
    writer.start()
    return writer


class AsyncDecisionWriter:
    """Bounded producer queue; all file work runs off the event loop."""

    def __init__(self, directory: Path, *, capacity: int = 1024, tz=None, clock=None, shutdown_timeout: float = 5.0, maintenance_interval: float = 3600, version=None, required_mount: Path | None = None):
        self.version = version
        self.entry_alias: str | None = None
        self.session_id = uuid4().hex
        self.files = DecisionFileWriter(directory, required_mount=required_mount)
        self.shutdown_timeout = shutdown_timeout
        self.maintenance_interval = maintenance_interval
        self.tz = tz
        self.clock = clock or (lambda: datetime.now().astimezone())
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=capacity)
        self.dropped = 0
        self.errors = 0
        self.sequence = 0
        self._task = None
        self._closing = False
        self._last_warning = float('-inf')

    def _warn_health(self) -> None:
        now = time.monotonic()
        if now - self._last_warning >= 300:
            self._last_warning = now
            _LOGGER.warning("PowerSync decision logging has lost records or encountered an error; dropped=%d errors=%d", self.dropped, self.errors)

    def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("writer already started")
        self._task = asyncio.create_task(self._run())

    def emit(self, stream: str, event: dict) -> bool:
        if self._closing or self._task is None:
            self.dropped += 1
            return False
        if stream not in {'ev', 'optimizer'} or event.get('event') not in {'pause', 'solve', 'first', 'lost', 'shared_pause_requested', 'battery_target_decision', 'solar_export_slot', 'solar_export_budget', 'solar_battery_floor', 'solar_rate_decision', 'dynamic_stop_requested', 'dynamic_stop_result', 'stop_observation', 'price_level_decision', 'smart_schedule_decision', 'ownership_claimed', 'ownership_released', 'ev_command', 'ownership_blocked', 'shared_policy_decision', 'shared_observation', 'optimizer_action', 'optimizer_action_result', 'command_handler_requested', 'command_handler_result', 'price_level_result', 'smart_schedule_policy', 'solar_production_state', 'sigenergy_curtailment_decision', 'sigenergy_curtailment_result', 'scheduled_policy', 'scheduled_price', 'solar_export_summary', 'smart_schedule_window', 'ownership_stop_blocked'}:
            self.dropped += 1
            self._warn_health()
            return False
        # Minimal prototype allowlist: production event schemas must expand this
        # explicitly before any control path connects to the writer.
        snapshot = {'event': event['event']}
        trace_id = event.get('trace_id')
        if isinstance(trace_id, str) and re.fullmatch(r'[0-9a-f]{32}', trace_id):
            snapshot['trace_id'] = trace_id
        for key in ('amps', 'requested_amps', 'grid_limit_kw', 'grid_power_kw',
                    'battery_target_kw', 'battery_effective_target_kw', 'battery_power_kw',
                    'battery_soc', 'solar_power_kw', 'home_load_kw', 'ev_power_kw',
                    'available_power_kw', 'planned_ev_kw', 'current_amps', 'min_amps', 'max_amps',
                    'current_soc', 'interval_hours', 'slot_index', 'grid_export_limit_w',
                    'solar_surplus_kw', 'export_price_per_kwh', 'remaining_headroom_kwh',
                    'deferred_kwh', 'eligible_replenishment_kwh', 'cheapest_replenishment_cost_per_kwh',
                    'deadline_target_kwh', 'deadline_capacity_remaining_kwh',
                    'max_charge_kw', 'capacity_kwh', 'efficiency', 'deadline_slot', 'max_grid_import_w',
                    'min_battery_soc', 'pause_battery_soc', 'allocated_surplus_kw', 'available_amps',
                    'executable_amps', 'optimizer_ceiling_amps', 'stop_delay_minutes', 'sustained_minutes',
                    'power_kw', 'observation_age_seconds', 'ev_soc', 'price_cents', 'recovery_soc',
                    'recovery_price_cents', 'opportunity_price_cents', 'target_soc', 'solar_power_w',
                    'grid_power_w', 'load_power_w', 'power_w', 'battery_charge_w', 'battery_discharge_w',
                    'export_price_cents', 'max_price_cents', 'low_surplus_seconds', 'high_surplus_seconds',
                    'selected_slots', 'horizon_slots', 'enter_threshold_cents', 'exit_threshold_cents', 'window_price_cents'):
            if key not in event:
                continue
            value = event[key]
            if value is None or type(value) in (int, float):
                if type(value) is float and not math.isfinite(value):
                    snapshot[key] = None
                    snapshot.setdefault('invalid_numeric_fields', []).append(key)
                else:
                    snapshot[key] = value
        for key in ('window_start', 'window_end', 'target_time'):
            value = event.get(key)
            if value is None and key in event:
                snapshot[key] = None
            elif isinstance(value, str) and len(value) <= 40:
                try:
                    datetime.fromisoformat(value)
                except ValueError:
                    pass
                else:
                    snapshot[key] = value
        for key in ('start_time', 'end_time'):
            value = event.get(key)
            if isinstance(value, str) and re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value):
                snapshot[key] = value
        if event.get('export_owner') in {'normal', 'dc_zero', 'manual_force', 'optimizer'}:
            snapshot['export_owner'] = event['export_owner']
        if event.get('production_state') in {'normal', 'restore_pending', 'external_control', 'blocked',
                                               'stop_pending', 'unsupported', 'limit_confirmed',
                                               'grid_unavailable', 'control_error'}:
            snapshot['production_state'] = event['production_state']
        for key in ('device_limit_confirmed', 'physical_converged', 'restore_required', 'grid_connected', 'enabled'):
            if key in event and (event[key] is None or type(event[key]) is bool):
                snapshot[key] = event[key]
        if event.get('reported_action') in {'self_consumption', 'charge', 'discharge', 'idle', 'no_discharge', 'solar_export', 'grid_charge', 'battery_export'}:
            snapshot['reported_action'] = event['reported_action']
        if event.get('planned_action') in {'self_consumption', 'charge', 'discharge', 'idle', 'no_discharge', 'solar_export', 'grid_charge', 'battery_export'}:
            snapshot['planned_action'] = event['planned_action']
        if event.get('source') in {'grid', 'solar', 'solar_surplus', 'battery', 'scheduled',
                                    'price_level', 'price_level_recovery', 'price_level_opportunity', 'grid_free', 'grid_offpeak',
                                    'grid_peak', 'grid_negative', 'grid_opportunistic', 'grid_deadline_fallback', 'waiting'}:
            snapshot['source'] = event['source']
        if event.get('evidence') in {'fresh_power', 'stale_or_missing_power', 'fresh_evac_state',
                                     'stale_or_missing_evac', 'selector_unresolved', 'unknown'}:
            snapshot['evidence'] = event['evidence']
        if event.get('origin') in {'powersync', 'external', 'unknown', 'settling'}:
            snapshot['origin'] = event['origin']
        if event.get('owner') in {'powersync', 'external'}:
            snapshot['owner'] = event['owner']
        if event.get('profile') in {'shared_ev_profile_a', 'shared_ev_profile_b'}:
            snapshot['profile'] = event['profile']
        if event.get('command') in {'start', 'stop', 'set_amps', 'release', 'external_policy_override',
                                     'external_handoff', 'stop_observed', 'stop_smart_schedule',
                                     'stop_scheduled_external', 'stop_smart_schedule_external'}:
            snapshot['command'] = event['command']
        if event.get('requested_mode') in {'solar_surplus', 'smart_schedule', 'smart_schedule_solar_surplus', 'price_level_recovery', 'price_level_opportunity', 'scheduled', 'price_level', 'manual', 'external', 'dynamic'}:
            snapshot['requested_mode'] = event['requested_mode']
        if event.get('owner_mode') in {'solar_surplus', 'smart_schedule', 'smart_schedule_solar_surplus', 'price_level_recovery', 'price_level_opportunity', 'scheduled', 'price_level', 'manual', 'external', 'dynamic'}:
            snapshot['owner_mode'] = event['owner_mode']
        if event.get('reason') in {'selected', 'grid_export_limit_blocked', 'insufficient_solar_surplus',
                                    'battery_headroom_exhausted', 'hard_charge_block',
                                    'non_positive_export_price', 'insufficient_cheaper_replenishment',
                                    'charge_by_time_target_protection', 'battery_below_pause_floor',
                                    'optimizer_zero', 'trial_ended', 'insufficient_surplus',
                                    'sustained_surplus_wait', 'surplus_available', 'surplus_stop_delay_elapsed',
                                    'surplus_stop_delay_wait', 'cycle_unavailable',
                                    'selector_changed', 'telemetry_unknown', 'solar_disabled', 'profile_unconfigured',
                                    'profile_solar_disabled', 'backend_mismatch', 'unplugged', 'solar_only',
                                    'above_price_cap', 'demand_window', 'price_policy_blocked', 'optimizer_disabled',
                                    'executor_unavailable', 'restore_in_progress', 'evaluation', 'price_level_disabled', 'away',
                                    'home_battery_low', 'price_policy', 'price_unavailable', 'scheduled_disabled', 'outside_schedule',
                                    'profit_max_disabled', 'insufficient_horizon', 'capability_unsupported', 'battery_limits_unknown',
                                    'monitoring_mode', 'adapter_unavailable', 'capability_check_failed', 'cleanup_pending',
                                    'zero_export_site', 'export_limit_not_configured', 'upstream_integration_not_loaded', 'owner_conflict', 'owner_missing'}:
            snapshot['reason'] = event['reason']
        if event.get('outcome') in {'returned', 'returned_true', 'not_confirmed', 'exception'}:
            snapshot['outcome'] = event['outcome']
        if event.get('charger_type') in {'generic', 'sigenergy'}:
            snapshot['charger_type'] = event['charger_type']
        if 'charging' in event and (event['charging'] is None or type(event['charging']) is bool):
            snapshot['charging'] = event['charging']
        if event.get('reported_state') in {'exception', 'charging', 'disabled', 'unselected_shared_profile',
                                      'no_soc', 'away', 'unplugged', 'complete', 'no_plan', 'waiting',
                                      'stopped', 'soc_unavailable', 'forecast_ready', 'started', 'wants_charge', 'normal', 'curtailed'}:
            snapshot['reported_state'] = event['reported_state']
        for key in ('selected', 'allow_grid_charge', 'allow_parallel', 'power_available', 'stop_charging', 'runtime_pause', 'should_charge', 'is_charging', 'success', 'allowed', 'time_critical', 'export_uneconomic', 'ev_headroom', 'write_pending', 'price_fallback'):
            if type(event.get(key)) is bool:
                snapshot[key] = event[key]
        for key in ('future_capacity_kwh', 'future_solar_capacity_kwh', 'future_grid_capacity_kwh',
                    'future_cost_per_kwh', 'import_prices',
                    'export_prices', 'solar_forecast', 'load_forecast', 'grid_export_limits_w',
                    'replenishment_slots', 'replenishment_used_kwh'):
            if key not in event:
                continue
            value = event[key]
            if value is None:
                snapshot[key] = None
            elif isinstance(value, list) and len(value) <= 1024 and all(x is None or type(x) in (int, float) for x in value):
                snapshot[key] = []
                for index, item in enumerate(value):
                    if type(item) is float and not math.isfinite(item):
                        snapshot[key].append(None)
                        snapshot.setdefault('invalid_numeric_fields', []).append(f'{key}[{index}]')
                    else:
                        snapshot[key].append(item)
        for key in ('hard_charge_blocks', 'grid_charge_allowed'):
            value = event.get(key)
            if isinstance(value, list) and len(value) <= 1024 and all(type(x) is bool for x in value):
                snapshot[key] = list(value)
        now = self.clock()
        self.sequence += 1
        snapshot.update(schema_version=1, sequence=self.sequence, version=self.version,
                        session_id=self.session_id, entry_alias=self.entry_alias, stream=stream,
                        timestamp_utc=now.astimezone(timezone.utc).isoformat(),
                        timestamp_local=now.astimezone(self.tz).isoformat())
        try:
            self.queue.put_nowait((stream, now.astimezone(self.tz).date(), snapshot))
        except asyncio.QueueFull:
            self.dropped += 1
            self._warn_health()
            return False
        return True

    def new_solver_recorder(self, currency: str):
        from .regression.capture import CaptureRecorder
        return CaptureRecorder(None, currency=currency, max_cycles=1, local_diagnostics=True)

    def emit_solver_capture(self, recorder, *, trace_id=None) -> bool:
        """Queue a private, closed-contract recorder; serialization is off-loop."""
        from .regression.capture import CaptureRecorder
        if type(recorder) is not CaptureRecorder or self._closing or self._task is None:
            self.dropped += 1
            if type(recorder) is CaptureRecorder:
                recorder.close()
            self._warn_health()
            return False
        now = self.clock()
        self.sequence += 1
        event = {'event': 'solver_capture', 'schema_version': 1, 'version': self.version,
                 'session_id': self.session_id, 'entry_alias': self.entry_alias, 'stream': 'optimizer',
                 'sequence': self.sequence,
                 'timestamp_utc': now.astimezone(timezone.utc).isoformat(),
                 'timestamp_local': now.astimezone(self.tz).isoformat()}
        if isinstance(trace_id, str) and re.fullmatch(r'[0-9a-f]{32}', trace_id):
            event['trace_id'] = trace_id
        try:
            self.queue.put_nowait(('optimizer', now.astimezone(self.tz).date(), (event, recorder)))
        except asyncio.QueueFull:
            self.dropped += 1
            recorder.close()
            self._warn_health()
            return False
        return True

    async def _run(self) -> None:
        last_day = None
        reported_dropped = 0
        reported_errors = 0
        try:
            initial_day = self.clock().astimezone(self.tz).date()
            await _disk_call(self.files.prune, initial_day)
            last_day = initial_day
        except Exception:
            self.errors += 1
            self._warn_health()
        while True:
            try:
                item = await asyncio.wait_for(self.queue.get(), self.maintenance_interval)
            except TimeoutError:
                try:
                    today = self.clock().astimezone(self.tz).date()
                    if today != last_day:
                        await _disk_call(self.files.prune, today)
                        last_day = today
                except Exception:
                    self.errors += 1
                    self._warn_health()
                continue
            try:
                if item is None:
                    return
                stream, day, event = item
                if day != last_day:
                    await _disk_call(self.files.prune, day)
                    last_day = day
                if isinstance(event, tuple):
                    event, recorder = event
                    try:
                        event['capture'] = await asyncio.to_thread(recorder.export)
                    finally:
                        recorder.close()
                await _disk_call(self.files.append, stream, day, event)
                if self.dropped != reported_dropped or self.errors != reported_errors:
                    gap_now = self.clock()
                    gap = {'event': 'diagnostic_gap', 'schema_version': 1, 'version': self.version,
                           'session_id': self.session_id, 'entry_alias': self.entry_alias, 'stream': stream,
                           'timestamp_utc': gap_now.astimezone(timezone.utc).isoformat(),
                           'timestamp_local': gap_now.astimezone(self.tz).isoformat(),
                           'after_sequence': event['sequence'], 'dropped_total': self.dropped,
                           'errors_total': self.errors}
                    try:
                        await _disk_call(self.files.append, stream, day, gap)
                    except Exception:
                        self.errors += 1
                        self._warn_health()
                    else:
                        reported_dropped, reported_errors = self.dropped, self.errors
            except Exception:
                self.errors += 1
                self.dropped += 1
                self._warn_health()
            finally:
                # If retention failed before a queued solver capture could be
                # exported, release it rather than retaining its large buffers.
                if item is not None and isinstance(item[2], tuple):
                    item[2][1].close()
                self.queue.task_done()

    async def close(self) -> None:
        self._closing = True
        if self._task is None:
            return
        try:
            async with asyncio.timeout(self.shutdown_timeout):
                await self.queue.put(None)
                await self._task
        except TimeoutError:
            # In-flight disk work may still finish in the executor. Do not
            # pretend the abandoned records were durably persisted.
            self.dropped += self.queue.qsize() + 1
            self._task.cancel()
