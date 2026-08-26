from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import secrets

from .config import load_config
from .delivery import render_review_batch
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
    review_parser = commands.add_parser("review-batch")
    review_parser.add_argument("--recipe", required=True)
    review_parser.add_argument("--batch-id", required=True)
    review_parser.add_argument("--count", type=int, default=10)
    review_parser.add_argument("--seed", type=int, required=True)
    review_parser.add_argument("--target-lufs", type=float, default=-22.0)
    review_parser.add_argument(
        "--output", type=Path, default=Path("audio/output/candidates")
    )
    audit_parser = commands.add_parser("ingredient-audit")
    audit_parser.add_argument("--registry", type=Path)
    audit_parser.add_argument("--host", default="127.0.0.1")
    audit_parser.add_argument("--port", type=int, default=8766)
    audit_parser.add_argument("--no-browser", action="store_true")
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "ingredient-audit":
        from .audit_server import run_server

        run_server(
            config_path=args.config,
            registry_path=args.registry,
            host=args.host,
            port=args.port,
            open_browser=not args.no_browser,
        )
        return

    config = load_config(args.config)
    if args.command == "validate":
        print(f"Valid: {len(config.assets)} assets, {len(config.profiles)} profiles, {len(config.recipes)} recipes")
        return

    if args.recipe not in config.recipes:
        raise SystemExit(f"Unknown recipe: {args.recipe}")
    if args.command == "review-batch":
        summary = render_review_batch(
            config,
            recipe_id=args.recipe,
            seeds=[args.seed + index for index in range(args.count)],
            batch_id=args.batch_id,
            output_root=args.output,
            target_lufs=args.target_lufs,
        )
        print(
            f"Rendered {summary['candidateCount']} audio-only review candidates "
            f"to {args.output / args.batch_id}"
        )
        return
    base_seed = args.seed if args.seed is not None else secrets.randbelow(2_147_483_647)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for index in range(args.count):
        seed = base_seed + index
        filename = f"{args.recipe}_{stamp}_{index + 1:03d}_seed-{seed}.wav"
        result = generate(config, args.recipe, seed, args.output / filename)
        print(
            f"{result.path} seed={result.seed} bed={result.bed_id} "
            f"gesture={result.gesture_id} gesture_start={result.gesture_start_sec:.3f}s "
            f"music={result.music_stem_id or 'none'} "
            f"music_start={result.music_start_sec if result.music_start_sec is not None else 'none'}"
        )


if __name__ == "__main__":
    main()
