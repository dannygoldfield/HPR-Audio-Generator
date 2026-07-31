from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import secrets

from .config import load_config
from .generator import generate


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hpr-audio")
    parser.add_argument("--config", type=Path, default=Path("config/generator.xml"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate")
    generate_parser = commands.add_parser("generate")
    generate_parser.add_argument("--recipe", required=True)
    generate_parser.add_argument("--count", type=int, default=10)
    generate_parser.add_argument("--seed", type=int)
    generate_parser.add_argument("--output", type=Path, default=Path("audio/output/candidates"))
    return parser


def main() -> None:
    args = _parser().parse_args()
    config = load_config(args.config)
    if args.command == "validate":
        print(f"Valid: {len(config.assets)} assets, {len(config.profiles)} profiles, {len(config.recipes)} recipes")
        return

    if args.recipe not in config.recipes:
        raise SystemExit(f"Unknown recipe: {args.recipe}")
    base_seed = args.seed if args.seed is not None else secrets.randbelow(2_147_483_647)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for index in range(args.count):
        seed = base_seed + index
        filename = f"{args.recipe}_{stamp}_{index + 1:03d}_seed-{seed}.wav"
        result = generate(config, args.recipe, seed, args.output / filename)
        print(
            f"{result.path} seed={result.seed} bed={result.bed_id} "
            f"gesture={result.gesture_id} gesture_start={result.gesture_start_sec:.3f}s"
        )


if __name__ == "__main__":
    main()

