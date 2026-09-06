from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .models import InstrumentType, __version__
from .okx import OKXPolicy, OKXPublicClient
from .storage import Store
from .universe import ScreenPolicy, screen_spot_universe


def _json(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def cmd_doctor(args: argparse.Namespace) -> int:
    checks = {
        "version": __version__,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "supported_python": (3, 11) <= sys.version_info[:2] < (3, 14),
        "capital_permissions": "NONE",
        "live_order_transport": False,
        "venue": "OKX",
    }
    _json(checks)
    return 0 if checks["supported_python"] else 2


def cmd_init(args: argparse.Namespace) -> int:
    store = Store(args.db)
    store.initialize()
    _json({"database": str(Path(args.db).resolve()), "audit_chain": store.verify_audit_chain()})
    return 0


def _load_policy(path: str | None) -> tuple[OKXPolicy, ScreenPolicy]:
    if path is None:
        return OKXPolicy(), ScreenPolicy()
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    okx = payload.get("okx", {})
    screen = payload.get("screen", {})
    return OKXPolicy(**okx), ScreenPolicy(**screen)


def cmd_okx_scan(args: argparse.Namespace) -> int:
    if not args.ack_network:
        raise SystemExit("refusing network access without --ack-network")
    okx_policy, screen_policy = _load_policy(args.policy)
    client = OKXPublicClient(okx_policy)
    instruments = client.instruments(InstrumentType.SPOT)
    quotes = client.tickers(InstrumentType.SPOT)
    ranked = screen_spot_universe(instruments, quotes, screen_policy)
    out = {
        "status": "PUBLIC_RESEARCH_SCAN_ONLY",
        "venue": "OKX",
        "instrument_count": len(instruments),
        "fresh_quote_count": len(quotes),
        "screened_count": len(ranked),
        "detail_candidates": [asdict(row) for row in ranked[: screen_policy.detail_limit]],
        "warning": "research priority is not a buy signal or expected-return ranking",
    }
    if args.out:
        target = Path(args.out)
        target.mkdir(parents=True, exist_ok=False)
        (target / "universe.json").write_text(
            json.dumps(out, indent=2, default=str, sort_keys=True), encoding="utf-8"
        )
    _json(out)
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    target = Path(args.out)
    target.mkdir(parents=True, exist_ok=False)
    payload = {
        "version": __version__,
        "mode": "SYNTHETIC",
        "network_calls": 0,
        "model_calls": 0,
        "orders": 0,
        "capital_permissions": "NONE",
        "message": "Use deterministic fixtures for CI; real-source and model conformance are separate gates.",
    }
    (target / "demo.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _json(payload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cairn", description="Cairn crypto research workbench")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="show local capability / safety status")
    doctor.set_defaults(func=cmd_doctor)

    init = sub.add_parser("init", help="initialize local research database")
    init.add_argument("--db", default="cairn.sqlite3")
    init.set_defaults(func=cmd_init)

    scan = sub.add_parser("okx-scan", help="run explicit public OKX spot-universe scan")
    scan.add_argument("--policy")
    scan.add_argument("--ack-network", action="store_true")
    scan.add_argument("--out")
    scan.set_defaults(func=cmd_okx_scan)

    demo = sub.add_parser("demo", help="write deterministic offline demo metadata")
    demo.add_argument("--out", required=True)
    demo.set_defaults(func=cmd_demo)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
