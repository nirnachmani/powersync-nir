"""Private-fork Actions must not run public-only or unused deployment jobs."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_private_validation_keeps_hassfest_but_not_public_hacs_action():
    source = (ROOT / ".github/workflows/validate.yml").read_text(encoding="utf-8")
    assert "validate-hassfest:" in source
    assert "home-assistant/actions/hassfest@" in source
    assert "validate-hacs:" not in source
    assert "hacs/action@" not in source
