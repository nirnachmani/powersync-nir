"""Durable, identity-fenced pending stops in an existing AutomationStore.

All callers must use this module for the private namespace. The lock serializes
only these helpers on the *same store object*: other AutomationStore writers do
not participate, and their concurrent saves are not globally serialized here.
A failed/cancelled save has an unknown disk outcome; replace the store object
with a freshly disk-loaded instance before using this namespace again. Episode
generations must be globally unique and never reused by the caller. A persisted
record is recovery evidence, not permission to issue a command or evidence of a
physical stop.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta
import inspect
import math
from typing import Any

STORAGE_KEY = "_shared_pending_stops"
PHYSICAL_IDS = frozenset({"generic_ev", "sigenergy_charger"})
PARAMETER_NAMES = frozenset({
    "charger_type", "charger_switch_entity", "charger_amps_entity",
    "charger_status_entity", "charger_power_entity", "sigenergy_charger_host",
    "sigenergy_charger_port", "sigenergy_charger_slave_id", "sigenergy_charger_type",
})
_FIELDS = frozenset({"generation", "binding_id", "profile_id", "owner_mode", "session_id",
                     "first_attempt_at", "attempt_count", "last_status", "last_attempt_at",
                     "parameters", "alerted", "revision"})
_OPTIONAL_FIELDS = frozenset({"binding_snapshot", "dispatch_at", "owner_kind",
                              "observed_session_token", "resolver_stop_lease_token"})
_IMMUTABLE = ("generation", "binding_id", "profile_id", "owner_mode", "session_id",
              "first_attempt_at", "parameters")
_LOCK_ATTR = "_shared_pending_stop_lock"
_POISON_ATTR = "_shared_pending_stop_save_uncertain"


class PendingStopError(Exception):
    """Storage cannot safely serve this request."""


class MalformedPendingStop(PendingStopError):
    """Persisted pending-stop data cannot safely be interpreted."""


class PendingStopConflict(PendingStopError):
    """Generation/revision changed or the episode identity was altered."""


def _store_parts(store: Any):
    if store is None or not isinstance(getattr(store, "_data", None), dict) or not callable(getattr(store, "async_save", None)):
        raise PendingStopError("automation store unavailable")
    if getattr(store, _POISON_ATTR, False):
        raise PendingStopError("save outcome uncertain; reload store before recovery")
    try:
        lock = getattr(store, _LOCK_ATTR, None)
        if lock is None:
            lock = asyncio.Lock()
            setattr(store, _LOCK_ATTR, lock)
    except (AttributeError, TypeError) as err:
        raise PendingStopError("store cannot hold pending-stop lock") from err
    return lock


def _timestamp(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.utcoffset() == timedelta(0)
    except (ValueError, OverflowError):
        return False


def _validate(record: Any) -> None:
    if not isinstance(record, dict) or not _FIELDS.issubset(record) or set(record) - _FIELDS - _OPTIONAL_FIELDS:
        raise MalformedPendingStop("invalid pending-stop record fields")
    if "binding_snapshot" in record and (not isinstance(record["binding_snapshot"], str) or not record["binding_snapshot"]):
        raise MalformedPendingStop("invalid binding snapshot")
    if record.get("owner_kind") not in (None, "external", "powersync"):
        raise MalformedPendingStop("invalid owner kind")
    for name in ("observed_session_token", "resolver_stop_lease_token"):
        if record.get(name) is not None and (not isinstance(record[name], str) or not record[name] or record[name] != record[name].strip()):
            raise MalformedPendingStop(f"invalid {name}")

    for name in ("generation", "binding_id", "profile_id", "owner_mode", "session_id", "last_status"):
        value = record[name]
        if not isinstance(value, str) or not value or value != value.strip():
            raise MalformedPendingStop(f"invalid {name}")
    if not _timestamp(record["first_attempt_at"]) or not _timestamp(record["last_attempt_at"]):
        raise MalformedPendingStop("timestamps must be UTC ISO strings")
    if record.get("dispatch_at") is not None and (not _timestamp(record["dispatch_at"]) or datetime.fromisoformat(record["dispatch_at"]) < datetime.fromisoformat(record["first_attempt_at"])):
        raise MalformedPendingStop("invalid dispatch timestamp")
    if datetime.fromisoformat(record["last_attempt_at"]) < datetime.fromisoformat(record["first_attempt_at"]):
        raise MalformedPendingStop("last attempt predates first attempt")
    if type(record["attempt_count"]) is not int or record["attempt_count"] < 1:
        raise MalformedPendingStop("invalid attempt count")
    if type(record["revision"]) is not int or record["revision"] < 1:
        raise MalformedPendingStop("invalid revision")
    if type(record["alerted"]) is not bool:
        raise MalformedPendingStop("invalid alert state")
    params = record["parameters"]
    if not isinstance(params, dict) or not set(params).issubset(PARAMETER_NAMES):
        raise MalformedPendingStop("invalid physical parameter names")
    for value in params.values():
        if type(value) not in (str, int, float, bool, type(None)) or (type(value) is float and not math.isfinite(value)):
            raise MalformedPendingStop("physical parameters must be finite JSON scalars")


def _records(store: Any) -> dict:
    data = getattr(store, "_data", None)
    if not isinstance(data, dict):
        raise PendingStopError("automation store unavailable")
    if STORAGE_KEY not in data:
        return {}
    records = data[STORAGE_KEY]
    if not isinstance(records, dict):
        raise MalformedPendingStop("invalid pending-stop namespace")
    for physical_id, record in records.items():
        if physical_id not in PHYSICAL_IDS:
            raise MalformedPendingStop("invalid physical id")
        _validate(record)
    return records


def _id(physical_id: str) -> None:
    if physical_id not in PHYSICAL_IDS:
        raise PendingStopError("expected a canonical supported physical id")


async def load_pending_stop(store: Any, physical_id: str) -> dict | None:
    """Return a detached record, None if absent; raise on unavailable/corrupt state."""
    _id(physical_id)
    async with _store_parts(store):
        _store_parts(store)  # recheck poison after waiting for another writer
        return deepcopy(_records(store).get(physical_id))


async def _save(store: Any, old_present: bool, old: Any, replacement: dict) -> None:
    data = store._data
    data[STORAGE_KEY] = replacement
    try:
        result = store.async_save()
        if not inspect.isawaitable(result):
            raise PendingStopError("automation store save is not awaitable")
        await result
    except BaseException:
        # Do not destroy a concurrent outsider's replacement. Unrelated top-level
        # writes are left intact. Disk may already have changed despite failure.
        if data.get(STORAGE_KEY) is replacement:
            if old_present:
                data[STORAGE_KEY] = old
            else:
                data.pop(STORAGE_KEY, None)
        setattr(store, _POISON_ATTR, True)
        raise


async def upsert_pending_stop(store: Any, physical_id: str, record: dict, *,
                              expected_generation: str | None, expected_revision: int | None) -> dict:
    """Create iff absent (both expectations None), otherwise CAS exact revision.

    Pass the returned record back when updating; revision is assigned here. The
    episode identity, first-attempt time and original physical parameters cannot
    change in place. A new generation requires deleting the previous episode.
    """
    _id(physical_id)
    async with _store_parts(store):
        _store_parts(store)
        old_present = STORAGE_KEY in store._data
        old = store._data.get(STORAGE_KEY)
        records = _records(store)
        current = records.get(physical_id)
        if current is None:
            if expected_generation is not None or expected_revision is not None:
                raise PendingStopConflict("record is absent")
            revision = 1
        else:
            if (expected_generation != current["generation"] or type(expected_revision) is not int
                    or expected_revision != current["revision"]):
                raise PendingStopConflict("stale generation or revision")
            revision = current["revision"] + 1
        if not isinstance(record, dict):
            raise MalformedPendingStop("record must be a dict")
        candidate = deepcopy(record)
        candidate["revision"] = revision
        _validate(candidate)
        if current is not None:
            if any(candidate[name] != current[name] for name in _IMMUTABLE):
                raise PendingStopConflict("episode identity or original parameters changed")
            if candidate.get("binding_snapshot") != current.get("binding_snapshot") or (current.get("dispatch_at") is not None and candidate.get("dispatch_at") != current.get("dispatch_at")):
                raise PendingStopConflict("binding or dispatch timestamp changed")
            if any(candidate.get(name) != current.get(name) for name in ("owner_kind", "observed_session_token", "resolver_stop_lease_token")):
                raise PendingStopConflict("external episode identity changed")
            if candidate["attempt_count"] < current["attempt_count"] or datetime.fromisoformat(candidate["last_attempt_at"]) < datetime.fromisoformat(current["last_attempt_at"]):
                raise PendingStopConflict("attempt history moved backwards")
        replacement = dict(records)
        replacement[physical_id] = candidate
        await _save(store, old_present, old, replacement)
        return deepcopy(candidate)


async def delete_pending_stop(store: Any, physical_id: str, *, expected_generation: str,
                              expected_revision: int) -> None:
    """Delete only the exact current episode revision; absent is a conflict."""
    _id(physical_id)
    async with _store_parts(store):
        _store_parts(store)
        records = _records(store)
        current = records.get(physical_id)
        if (current is None or expected_generation != current["generation"]
                or type(expected_revision) is not int or expected_revision != current["revision"]):
            raise PendingStopConflict("stale or missing episode")
        replacement = dict(records)
        del replacement[physical_id]
        await _save(store, True, store._data[STORAGE_KEY], replacement)
