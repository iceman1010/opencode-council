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

    parser.add_argument(
        "--refresh-cache",
        action="store_true",
        help="Clear and rebuild tool cache then exit",
    )
    parser.add_argument(
        "--use-stale-cache",
        action="store_true",
        help="Use existing cache even if expired (skip rebuild)",
    )
    parser.add_argument(
        "--version", "-v", action="store_true", help="Show version number and exit"
    )

    args = parser.parse_args()

    if args.version:
        try:
            from importlib.metadata import version

            package_version = version("opencode-council")
        except ImportError:
            # Fallback for Python < 3.8
            import pkg_resources

            package_version = pkg_resources.get_distribution("opencode-council").version
        print(f"OpenCode Council v{package_version}")
        return

    if args.refresh_cache:
        from opencode_council.tools import ToolDiscovery

        print("Clearing existing tool cache...")
        cache_path = Path.home() / ".cache" / "opencode-council" / "tools_cache.json"
        if cache_path.exists():
            os.unlink(cache_path)
            print("Cache file deleted")
        else:
            print("No existing cache file found")

        print("Rebuilding tool cache...")
        discovery = ToolDiscovery()
        tools = discovery.discover_all(cache_ttl=0)
        print(f"Cache rebuilt successfully, found {len(tools)} tools")
        for tool_name, tool in tools.items():
            print(f"  - {tool_name}: {len(tool.available_models)} models")
        return

    try:
        if args.task and args.model:
            # Run directly from CLI without TUI
            from opencode_council.config import ConfigManager
            from opencode_council.execution import ExecutionEngine

            manager = ConfigManager()
            config = manager.load()
            config.debug_logging = True

            run_dir = manager.create_run_dir(args.output_dir)
            print(f"Running task in: {run_dir}")
            print(f"Models: {', '.join(args.model)}")

            engine = ExecutionEngine(config, run_dir)
            engine.prepare_models(args.model)
            engine.set_task(args.task)

            async def run():
                print("Running analysis phase...")
                await engine.run_analysis_phase()
                print("Running plan phase...")
                await engine.run_plan_phase()
                print("Running commentary phase...")
                await engine.run_commentary_phase()

                failed = engine.get_failed_models()
                completed = engine.get_completed_models()

                print(f"\n✅ Completed: {len(completed)} models")
                print(f"❌ Failed: {len(failed)} models")
                for name, error in failed:
                    print(f"  {name}: {error}")

                print(f"\nAll output written to: {run_dir}")
                print(f"Debug log: {run_dir / 'debug.log'}")

            asyncio.run(run())
            return

        from opencode_council.tui import run_app

        if args.use_stale_cache:
            from opencode_council.tools import ToolDiscovery
            discovery = ToolDiscovery()
            tools = discovery.discover_all(use_expired=True)
            print(f"Using stale cache with {len(tools)} tools")
            for tool_name, tool in tools.items():
                print(f"  - {tool_name}: {len(tool.available_models)} models")
            run_app(skip_cache_rebuild=True)
        else:
            run_app()

    except Exception as e:
        with open("/tmp/opencode_council_error.log", "w") as f:
            f.write(f"Exception: {e}\n")
            f.write(traceback.format_exc())
        raise


if __name__ == "__main__":
    main()