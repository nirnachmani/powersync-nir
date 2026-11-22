"""Site-specific solar model must be bounded and provider-scoped."""
import importlib.util
from pathlib import Path
from datetime import datetime

P = Path(__file__).resolve().parents[1] / 'custom_components/power_sync/optimization/solar_site_model.py'

def test_model_applies_only_to_enabled_open_meteo_and_keeps_zero():
    spec = importlib.util.spec_from_file_location('solar_site_model_test', P)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    t = datetime.fromisoformat('2026-06-01T12:00:00+09:30')
    assert module.adjust_site_forecast([0.0, 5.0], t, 30, False, 'open_meteo') == [0.0, 5.0]
    assert module.adjust_site_forecast([0.0, 5.0], t, 30, True, 'solcast') == [0.0, 5.0]
    p = module.adjust_site_forecast([0.0, 5.0], t, 30, True, 'open_meteo')
    assert p[0] == 0.0
    assert 0.0 <= p[1] <= 15.0
    assert p[1] != 5.0
