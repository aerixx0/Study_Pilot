"""Source and Windows installer entry point."""

import sys

from studypilot.cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or ["start"]))
