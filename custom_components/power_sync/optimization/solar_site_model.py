"""Fixed, site-specific Open-Meteo solar forecast model.

The exported trees are a numerically equivalent representation of the
chronologically selected histogram gradient booster; no ML dependency is
needed at runtime. Training covers forecast power from 1 to 10 kW only.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache
import json
import math
from pathlib import Path

MODEL_ID = 'open-meteo-site-2026-09-12-v1'

@lru_cache(maxsize=1)
def _model():
    with Path(__file__).with_name('solar_site_model_data.json').open(encoding='utf-8') as stream:
        model = json.load(stream)
    if model['model'] != MODEL_ID:
        raise ValueError('unexpected solar model version')
    return model

def _predict(forecast_kw: float, timestamp: datetime) -> float:
    data = _model()
    angle = 2 * math.pi * (timestamp.timetuple().tm_yday - 1) / 365.25
    features = [forecast_kw, math.sin(angle), math.cos(angle), timestamp.hour + timestamp.minute / 60]
    value = data['baseline']
    for tree in data['trees']:
        i = 0
        while not tree[i][5]:
            node = tree[i]
            i = node[3] if features[node[1]] <= node[2] else node[4]
        value += tree[i][0]
    return max(0.0, value)

def adjust_site_forecast(forecast: list[float], start: datetime, interval_minutes: int, enabled: bool, source: str | None) -> list[float]:
    """Apply only inside the training-domain, retaining unsupported values."""
    if not enabled or source != 'open_meteo':
        return list(forecast)
    result = []
    for index, value in enumerate(forecast):
        number = float(value)
        if not math.isfinite(number) or not 1 <= number <= 10:
            result.append(value)
        else:
            timestamp = (start.astimezone(timezone.utc) + timedelta(minutes=index * interval_minutes)).astimezone(start.tzinfo)
            result.append(_predict(number, timestamp))
    return result
