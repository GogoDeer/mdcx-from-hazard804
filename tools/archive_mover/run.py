"""Unified launcher for Archive Mover (auto-detects GUI or CLI mode)."""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to sys.path so imports work properly
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from tools.archive_mover.cli import run_cli  # noqa: E402
from tools.archive_mover.gui import run_gui  # noqa: E402


def main():
    # If explicitly asked for GUI, or no arguments provided, launch GUI
    if len(sys.argv) == 1 or (len(sys.argv) == 2 and sys.argv[1] in ("--gui", "-g")):
        try:
            return run_gui()
        except Exception as e:
            print(f"Failed to start GUI ({e}), falling back to CLI...")
            return run_cli()
    else:
        return run_cli()


if __name__ == "__main__":
    sys.exit(main())
