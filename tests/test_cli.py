from pathlib import Path

import pytest

from cairn.cli import main


def test_doctor_is_offline(capsys):
    assert main(["doctor"]) == 0
    output = capsys.readouterr().out
    assert '"capital_permissions": "NONE"' in output
    assert '"venue": "OKX"' in output


def test_demo_writes_synthetic_metadata(tmp_path: Path):
    out = tmp_path / "demo"
    assert main(["demo", "--out", str(out)]) == 0
    text = (out / "demo.json").read_text(encoding="utf-8")
    assert '"network_calls": 0' in text
    assert '"orders": 0' in text


def test_okx_scan_refuses_implicit_network():
    with pytest.raises(SystemExit, match="ack-network"):
        main(["okx-scan"])


def test_init_creates_auditable_database(tmp_path: Path):
    db = tmp_path / "cairn.sqlite3"
    assert main(["init", "--db", str(db)]) == 0
    assert db.exists()
