"""Long-retention forecast observations must not be mixed with decision logs."""
import importlib.util
from pathlib import Path
from datetime import date

P = Path(__file__).resolve().parents[1] / 'custom_components/power_sync/optimization/solar_forecast_monitor.py'

def test_writer_uses_separate_retention_and_preserves_current_data(tmp_path):
    spec = importlib.util.spec_from_file_location('forecast_monitor_test', P)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    writer = module.SolarForecastFiles(tmp_path)
    writer.append(date(2026, 11, 22), {'type': 'sample', 'actual_kw': 3})
    assert (tmp_path / 'solar-2026-11-22.jsonl').read_text().strip() == '{"type":"sample","actual_kw":3}'
    (tmp_path / 'solar-2023-11-20.jsonl').write_text('{}\n')
    (tmp_path / 'optimizer-2023-11-20.jsonl').write_text('{}\n')
    writer.prune(date(2026, 11, 22))
    assert not (tmp_path / 'solar-2023-11-20.jsonl').exists()
    assert (tmp_path / 'optimizer-2023-11-20.jsonl').exists()


def test_unavailable_mount_does_not_write_into_local_directory(tmp_path):
    import pytest
    spec = importlib.util.spec_from_file_location('forecast_monitor_missing_test', P)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = tmp_path / 'missing' / 'solar-forecast'
    writer = module.SolarForecastFiles(output, required_mount=tmp_path / 'missing')
    with pytest.raises(OSError):
        writer.append(date(2026, 11, 22), {'type': 'sample'})
    assert not output.exists()
