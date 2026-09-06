from __future__ import annotations

import os
import re
from pathlib import Path

from cairn.exact import fraction_decimal
import run_full_paper_cycle_v4 as runner

runner.D = fraction_decimal
runner.b.D = fraction_decimal

_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-(CAIRN-\d{2})$")


def stage_identity() -> None:
    marker = Path(".cairn/current-cycle.txt")
    if not marker.exists():
        return
    cycle_id = marker.read_text(encoding="utf-8").strip()
    match = _PATTERN.fullmatch(cycle_id)
    if match is None:
        raise RuntimeError(f"INVALID_CAIRN_CYCLE_ID {cycle_id}")
    os.environ["CAIRN_CYCLE_ID"] = cycle_id
    os.environ["CAIRN_RUNNER_ID"] = match.group(1)


if __name__ == "__main__":
    stage_identity()
    raise SystemExit(runner.main())
