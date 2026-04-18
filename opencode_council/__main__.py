"""Main entry point for OpenCode-Council with error logging."""

import sys
import os
import traceback
import argparse
import asyncio
from pathlib import Path


def main():
    """Run the application."""
    parser = argparse.ArgumentParser(
        description="OpenCode Council - Run multiple LLMs in parallel"
    )
    parser.add_argument("--task", type=str, help="Task to execute")
    parser.add_argument(
        "--model",
        action="append",
        default=[],
        help="Model to use (can specify multiple)",
    )
    parser.add_argument(
        "--output-dir", type=str, default="council", help="Output directory"
    )
    parser.add_argument("--no-debug", action="store_true", help="Disable debug logging")

    args = parser.parse_args()

    try:
        if args.task and args.model:
            # Run directly from CLI without TUI
            from opencode_council.config import ConfigManager
            from opencode_council.execution import ExecutionEngine

            manager = ConfigManager()
            config = manager.load()
            config.debug_logging = not args.no_debug

            run_dir = manager.create_run_dir(args.output_dir)
            print(f"Running task in: {run_dir}")
            print(f"Models: {', '.join(args.model)}")

            engine = ExecutionEngine(config, run_dir)
            engine.prepare_models(args.model)
            engine.set_task(args.task)

            async def run():
                await engine.run_analysis_phase()
                await engine.run_plan_phase()
                await engine.run_commentary_phase()

                failed = engine.get_failed_models()
                completed = engine.get_completed_models()

                print(f"\nCompleted: {len(completed)} models")
                print(f"Failed: {len(failed)} models")
                for name, error in failed:
                    print(f"  {name}: {error}")

                print(f"\nOutput written to: {run_dir}")

            asyncio.run(run())

        else:
            # Launch TUI interface
            from opencode_council.tui import run_app

            run_app()

    except Exception as e:
        with open("/tmp/opencode_council_error.log", "w") as f:
            f.write(f"Exception: {e}\n")
            f.write(traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
