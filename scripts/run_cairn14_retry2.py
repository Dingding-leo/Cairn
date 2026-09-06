from __future__ import annotations

from cairn.exact import fraction_decimal
import run_full_paper_cycle_v2 as base

base.D = fraction_decimal

import run_cairn14_retry as retry


if __name__ == "__main__":
    raise SystemExit(retry.main())
