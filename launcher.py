"""Entry point for the Windows .exe: start the dashboard and open it in the browser."""
import sys
import traceback

from stellar_dashboard.server import main

if __name__ == "__main__":
    try:
        main(["--open", *sys.argv[1:]])
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        input("\nThe dashboard stopped with an error (above). Press Enter to close this window.")
