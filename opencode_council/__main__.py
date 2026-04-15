"""Main entry point for OpenCode-Council with error logging."""

import sys
import os
import traceback


def main():
    """Run the application."""
    try:
        from opencode_council.tui import run_app

        run_app()
    except Exception as e:
        with open("/tmp/opencode_council_error.log", "w") as f:
            f.write(f"Exception: {e}\n")
            f.write(traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
