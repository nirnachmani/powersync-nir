"""Separate long-retention solar forecast and observation records.

File operations use one bounded daemon worker: an unavailable NAS must never
block the optimizer or fill local storage. Forecast snapshots and observations
are timestamped independently for retrospective lead-time alignment.
"""
from __future__ import annotations
from datetime import date, timedelta
import json
import logging
import os
from pathlib import Path
import queue
import re
import threading

_LOGGER = logging.getLogger(__name__)
_NAMES = re.compile(r'^solar-(\d{4}-\d{2}-\d{2})\.jsonl$')

class SolarForecastFiles:
    def __init__(self, directory: Path, required_mount: Path | None = None):
        self.directory = Path(directory)
        self.required_mount = required_mount
    def _check(self):
        if self.required_mount is not None and not os.path.ismount(self.required_mount):
            raise OSError('solar forecast NAS mount unavailable')
    def append(self, day: date, record: dict):
        self._check()
        line = json.dumps(record, separators=(',', ':'), allow_nan=False)
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / f'solar-{day.isoformat()}.jsonl').open('a', encoding='utf-8') as f:
            f.write(line + '\n')
    def prune(self, today: date):
        self._check()
        if not self.directory.exists():
            return
        try:
            cutoff = today.replace(year=today.year - 2)
        except ValueError:
            cutoff = today.replace(year=today.year - 2, day=28)
        for p in self.directory.iterdir():
            m = _NAMES.fullmatch(p.name)
            if m and not p.is_symlink() and p.is_file():
                try:
                    if date.fromisoformat(m.group(1)) < cutoff:
                        p.unlink()
                except ValueError:
                    continue

class SolarForecastMonitor:
    def __init__(self, files: SolarForecastFiles):
        self.files = files
        self.queue = queue.Queue(maxsize=128)
        self.dropped = 0
        self.errors = 0
        self.written = 0
        self.excluded = 0
        self.last_write_failed = False
        self.last_day = None
        self._thread = threading.Thread(target=self._run, name='powersync-solar-monitor', daemon=True)
        self._thread.start()
    def emit(self, day: date, record: dict) -> bool:
        try:
            self.queue.put_nowait((day, record))
            return True
        except queue.Full:
            self.dropped += 1
            _LOGGER.warning('Solar forecast monitor queue full; dropped=%s', self.dropped)
            return False
    def _run(self):
        while True:
            day, record = self.queue.get()
            try:
                if day != self.last_day:
                    self.files.prune(day)
                    self.last_day = day
                self.files.append(day, record)
                self.written += 1
                self.last_write_failed = False
                if record.get('known_exclusion') is not None:
                    self.excluded += 1
            except (OSError, ValueError, TypeError):
                self.errors += 1
                self.dropped += 1
                self.last_write_failed = True
                _LOGGER.warning('Solar forecast monitoring write failed; dropped=%s errors=%s', self.dropped, self.errors)
            finally:
                self.queue.task_done()

_monitor = None
_lock = threading.Lock()
def get_solar_monitor():
    global _monitor
    with _lock:
        if _monitor is None:
            mount = Path('/share/NAS_Backup')
            _monitor = SolarForecastMonitor(SolarForecastFiles(mount / 'power_sync_diagnostics' / 'solar-forecast', mount))
        return _monitor

def solar_monitor_status():
    monitor = _monitor
    if monitor is None:
        return {"state": "not_started", "written": 0, "excluded": 0, "dropped": 0, "errors": 0}
    return {"state": "degraded" if monitor.last_write_failed else "active", "written": monitor.written, "excluded": monitor.excluded, "dropped": monitor.dropped, "errors": monitor.errors}
