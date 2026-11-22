"""The site-model flow and its opt-in must be present on the real coordinator."""
from pathlib import Path

def test_optimizer_applies_site_model_before_nowcast_and_learning():
    text = (Path(__file__).resolve().parents[1] / 'custom_components/power_sync/optimization/coordinator.py').read_text()
    start = text.index('raw_solar_forecast = list(solar_forecast)')
    end = text.index('adjusted_solar_forecast = list(solar_forecast)', start)
    flow = text[start:end]
    assert flow.index('_apply_solar_site_model') < flow.index('_observe_solar_forecast_accuracy') < flow.index('_apply_solar_nowcast_derate')

def test_weather_settings_expose_opt_in():
    text = (Path(__file__).resolve().parents[1] / 'custom_components/power_sync/config_flow.py').read_text()
    section = text[text.index('async def async_step_weather_options'):]
    assert section.count('CONF_SOLAR_SITE_MODEL_ENABLED') >= 2
