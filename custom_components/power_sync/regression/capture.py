"""Default-off, memory-only solver observation. Capture failure is expendable.

Attach a recorder explicitly through ``record_cycle`` in a local test/developer
harness, or to a coordinator's ``_regression_recorder``. No transport, files,
credentials, HA services or device clients are used here.
"""
from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
from inspect import signature
import re
import time
from threading import RLock

from .contract import (
    Codec, ContractError, INPUT_FIELDS, MAX_BYTES, SOLVE_MUTATIONS, VERSION,
    SOURCE_FIELDS, canonical, decision_clock, digest, schedule_snapshot, state_snapshot,
)


_SAFE_CAPTURE_ERRORS = frozenset({
    "unsupported_signature", "missing_decision_clock", "invalid_decision_time",
    "unsupported_solver_options", "unsupported_stage", "unsupported_cycle_outcome",
    "unsupported_manual_fields", "unsupported_dataclass", "unsupported_value",
    "unsupported_key", "unsupported_text", "unsupported_identity", "unsupported_timezone",
    "nonfinite_value", "naive_timestamp", "array_limit", "capture_limit",
    "missing_optimizer_state",
})


def _safe_error_reason(error):
    """Expose only fixed contract codes, never exception payloads."""
    if type(error) is ContractError and str(error) in _SAFE_CAPTURE_ERRORS:
        return str(error)
    return "unexpected_capture_error"


def expendable(function):
    """Serialize observation, but NEVER wait for another capture thread.

    In particular cancellation/restart on the event loop cannot wait for an
    orphaned executor snapshot. Contention cancels observation, not control.
    """
    @wraps(function)
    def guarded(self, *args, **kwargs):
        if getattr(self,'closed',False):
            return None
        if not self._lock.acquire(blocking=False):
            self._note_error("capture_lock_contended")
            self._drop(detach=True)
            if function.__name__ == "start_cycle":
                self.generation += 1
                self.dropped += 1  # This new cycle was never admitted either.
            return None
        cycle = self.active
        try:
            try:
                return function(self, *args, **kwargs)
            except Exception as error:
                self._note_error(_safe_error_reason(error))
                self._drop(cycle)
                if self.active is not cycle:
                    self._drop()
                return None
        finally:
            self._lock.release()
    return guarded


class CaptureRecorder:
    """Bounded whole-cycle admission; export is explicit and off the solve path."""

    def __init__(self, source, *, currency, max_cycles=4, max_bytes=MAX_BYTES, local_diagnostics=False):
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise ContractError("currency_required")
        if not 1 <= max_cycles <= 32 or not 1024 <= max_bytes <= MAX_BYTES:
            raise ContractError("invalid_budget")
        if source is None and local_diagnostics:
            self.source = None  # Not a source-bound replay artifact.
        else:
            if not isinstance(source, dict) or set(source) != SOURCE_FIELDS:
                raise ContractError("invalid_source_binding")
            for key, value in source.items():
                pattern = r"[a-f0-9]{64}" if key.endswith("sha256") else r"[a-zA-Z0-9_.+-]{1,64}"
                if type(value) is not str or not re.fullmatch(pattern, value):
                    raise ContractError("invalid_source_binding")
            self.source = dict(source)
        self.currency = currency
        self._lock = RLock()
        self.max_cycles, self.max_bytes = max_cycles, max_bytes
        self.cycles = deque()
        self.active = None
        self.generation = 0
        self.errors = 0
        self.error_reasons = {}
        self.local_diagnostics = local_diagnostics
        self.dropped = 0
        self.capture_seconds = 0.0
        self._retained_bytes = 0
        self.closed = False
        self.pending = {}

    def _note_error(self, reason):
        self.errors += 1
        self.error_reasons[reason] = self.error_reasons.get(reason, 0) + 1

    def close(self):
        """Erase retained observation copies without waiting for a solver thread."""
        self.closed=True
        self._drop(detach=True)
        for ticket in tuple(self.pending.values()):
            ticket.clear()
        self.pending.clear()
        self.cycles.clear()
        self._retained_bytes=0

    @expendable
    def start_cycle(self):
        self.generation += 1
        if self.active is not None and self.active["complete"]:
            self.dropped += 1
        self.active = {"generation": self.generation, "attempts": [], "stages": [],
                       "complete": True, "bytes": 0, "outstanding": 0}
        if len(self.cycles) >= self.max_cycles or self._retained_bytes >= self.max_bytes:
            self._drop()

    def _drop(self, cycle=None, *, detach=False):
        # A contention path must not acquire the executor's lock. The complete
        # flag is a cancellation marker, checked again before every admission.
        cycle = self.active if cycle is None else cycle
        if cycle is not None and cycle["complete"]:
            self.dropped += 1
            cycle["complete"] = False
            if not detach:
                cycle.update(attempts=[], stages=[], bytes=0)
        if detach and self.active is cycle:
            self.active = None

    @expendable
    def begin(self, optimizer, arguments, *, provided_inputs=None, decision_time=None):
        start = time.monotonic()
        try:
            cycle = self.active
            if cycle is None or not cycle["complete"]:
                return None
            unknown = set(arguments) - set(INPUT_FIELDS)
            missing = set(INPUT_FIELDS) - set(arguments)
            if (unknown or missing) and not self.local_diagnostics:
                raise ContractError("unsupported_signature")
            unsupported = sorted(
                name if type(name) is str and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name)
                else "unrecognized_input" for name in unknown
            )
            unsupported.extend(sorted(missing))
            if not isinstance(decision_time, datetime) or decision_time.tzinfo is None or decision_time.utcoffset() is None:
                raise ContractError("missing_decision_clock")
            clock = {"decision_time": decision_time.isoformat(), "decision_timezone": getattr(decision_time.tzinfo, "key", None)}
            decision_clock(clock)
            provided = list(arguments) if provided_inputs is None else list(provided_inputs)
            if any(type(name) is not str for name in provided) or len(set(provided)) != len(provided):
                raise ContractError("unsupported_signature")
            provided = [name for name in provided if name in INPUT_FIELDS]
            codec = Codec()
            inputs = {}
            for key in INPUT_FIELDS:
                if key not in arguments:
                    continue
                aliases = dict(codec.aliases)
                try:
                    inputs[key] = codec.encode(arguments[key], key)
                except ContractError as error:
                    if not self.local_diagnostics or str(error) == "capture_limit":
                        raise
                    codec.aliases = aliases
                    unsupported.append(key)
                    self._note_error(_safe_error_reason(error))
            state = state_snapshot(optimizer, codec)
            if cycle is not self.active or not cycle["complete"]:
                return None
            if self._retained_bytes + cycle["bytes"] + codec.bytes > self.max_bytes:
                self._drop()
                return None
            cycle["outstanding"] += 1
            ticket = {"generation": cycle["generation"], "cycle": cycle, "codec": codec, "inputs": inputs,
                    "state": state, **clock, "provided_inputs": provided,
                    "unsupported_inputs": unsupported, "arguments": arguments}
            if self.closed or cycle is not self.active or not cycle['complete']:
                ticket.clear();return None
            self.pending[id(ticket)]=ticket
            if self.closed:
                ticket.clear();self.pending.pop(id(ticket),None);return None
            return ticket
        finally:
            self.capture_seconds += time.monotonic() - start

    @expendable
    def finish(self, ticket, optimizer, result=None, error=None):
        start = time.monotonic()
        try:
            if ticket is None:
                return
            cycle = ticket["cycle"]
            if cycle is not self.active or ticket["generation"] != cycle["generation"] or not cycle["complete"]:
                return
            cycle["outstanding"] -= 1
            codec = ticket["codec"]
            check = Codec()
            check.aliases = dict(codec.aliases)
            after = state_snapshot(optimizer, check)
            now_inputs = {key: check.encode(ticket["arguments"][key], key) for key in ticket["inputs"]}
            torn = now_inputs != ticket["inputs"] or any(
                after.get(key) != value for key, value in ticket["state"].items() if key not in SOLVE_MUTATIONS
            )
            rows = schedule_snapshot(result.schedule, codec) if result is not None else []
            if cycle is not self.active or not cycle["complete"]:
                return
            if self._retained_bytes + cycle["bytes"] + codec.bytes > self.max_bytes:
                self._drop()
                return
            exception = None
            if error is not None:
                name = type(error).__name__
                exception = name if name in ("ValueError", "RuntimeError", "TimeoutError", "CancelledError", "KeyboardInterrupt") else "other"
            output = {"schedule": rows, "feasible": bool(result.feasible) if result is not None else None,
                      "solver": result.solver_used if result is not None and result.solver_used in ("highs", "greedy") else None,
                      "exception": exception}
            body = {"schema_version": VERSION, "layer": "solver_v1", "source": self.source,
                    "decision_time": ticket["decision_time"], "currency": self.currency,
                    "decision_timezone": ticket["decision_timezone"], "provided_inputs": ticket["provided_inputs"],
                    "inputs": ticket["inputs"], "state": ticket["state"],
                    "outcome": "exception" if error is not None else ("feasible" if result.feasible else "infeasible"),
                    "result": output, "coverage": {"complete": not torn and not ticket["unsupported_inputs"] and bool(ticket["arguments"].get("schedule_timestamps")),
                        "torn": torn, "stages": ["solver_raw"], "not_covered": ["coordinator", "hardware", "counterfactual"]}}
            if ticket["unsupported_inputs"]:
                body["coverage"]["unsupported_inputs"] = ticket["unsupported_inputs"]
            cycle["attempts"].append(body)
            cycle["bytes"] += codec.bytes
        finally:
            if ticket is not None:
                self.pending.pop(id(ticket),None)
            self.capture_seconds += time.monotonic() - start

    @expendable
    def record_stage(self, stage, schedule):
        if self.active is None or not self.active["complete"]:
            return
        if stage not in ("committed", "post_solve"):
            raise ContractError("unsupported_stage")
        codec = Codec()
        rows = schedule_snapshot(schedule, codec)
        if self._retained_bytes + self.active["bytes"] + codec.bytes > self.max_bytes:
            self._drop()
            return
        self.active["stages"].append({"stage": stage, "schedule": rows})
        self.active["bytes"] += codec.bytes

    @expendable
    def finish_cycle(self, outcome):
        if self.active is None:
            return
        cycle, self.active = self.active, None
        if outcome not in ("committed", "aborted"):
            raise ContractError("unsupported_cycle_outcome")
        cycle["outcome"] = outcome
        if cycle["outstanding"] or not cycle["complete"] or not cycle["attempts"]:
            if cycle["complete"]:
                self.dropped += 1
            return
        self.cycles.append(cycle)
        self._retained_bytes += cycle["bytes"]

    def export(self):
        """Canonicalize only when explicitly exported, never while solving."""
        with self._lock:
            ready = [cycle for cycle in self.cycles if cycle["complete"]]
            counters = {"errors": self.errors, "dropped_cycles": self.dropped,
                        "error_reasons": dict(self.error_reasons),
                        "capture_seconds": self.capture_seconds, "estimated_bytes": self._retained_bytes}
        cycles = []
        for cycle in ready:
            attempts = []
            for body in cycle["attempts"]:
                attempts.append({**body, "digest": digest(body)})
            cycles.append({"outcome": cycle["outcome"], "attempts": attempts, "stages": cycle["stages"]})
        # Return detached primitives: callers cannot mutate the recorder.
        import json
        return json.loads(canonical({"schema_version": VERSION, "cycles": cycles,
            **counters}))


def capture_attempt(function):
    """Keep the original call, arguments, result and exceptions untouched."""
    call_signature = signature(function)

    @wraps(function)
    def observed(self, *args, **kwargs):
        recorder = getattr(self, "_regression_recorder", None)
        if recorder is None:
            return function(self, *args, **kwargs)
        ticket = None
        try:
            options = function.__globals__.get("_SOLVER_BENCHMARK")
            if options is not None and options.get() is not None:
                raise ContractError("unsupported_solver_options")
            bound = call_signature.bind(self, *args, **kwargs)
            provided = [name for name in bound.arguments if name != "self"]
            bound.apply_defaults()
            ticket = recorder.begin(self, {k: v for k, v in bound.arguments.items() if k != "self"},
                                    provided_inputs=provided, decision_time=function.__globals__["dt_util"].now())
        except Exception as error:
            recorder._note_error(_safe_error_reason(error))
            recorder._drop()
        try:
            result = function(self, *args, **kwargs)
        except BaseException as error:
            try:
                recorder.finish(ticket, self, error=error)
            except Exception as capture_error:
                recorder._note_error(_safe_error_reason(capture_error))
                recorder._drop()
            raise
        try:
            recorder.finish(ticket, self, result=result)
        except Exception as error:
            recorder._note_error(_safe_error_reason(error))
            recorder._drop()
        return result

    return observed


@contextmanager
def record_cycle(optimizer, recorder):
    """Local developer/test activation, restoring any previous observer."""
    prior = getattr(optimizer, "_regression_recorder", None)
    optimizer._regression_recorder = recorder
    recorder.start_cycle()
    try:
        yield
    finally:
        recorder.finish_cycle("aborted")
        optimizer._regression_recorder = prior
