"""Main entry point for Gnome Connection Manager."""

import os
import sys
from pathlib import Path


def run(argv: list[str] | None = None) -> int:
    """Run the Gnome Connection Manager application.

    Args:
        argv: Command line arguments (defaults to sys.argv)

    Returns:
        Exit code
    """
    if argv is None:
        argv = sys.argv

    # Set up paths for resources
    # Check if running from source or installed
    app_dir = Path(__file__).parent
    data_dir = app_dir.parent.parent / "data"

    # If data directory doesn't exist, try installed location
    if not data_dir.exists():
        data_dir = Path("/usr/share/gnome-connection-manager")

    # Set environment variables for the app to find resources
    os.environ.setdefault("GCM_DATA_DIR", str(data_dir))
    os.environ.setdefault("GCM_GLADE_DIR", str(data_dir / "ui"))
    os.environ.setdefault("GCM_SCRIPTS_DIR", str(data_dir / "scripts"))
    os.environ.setdefault("GSETTINGS_SCHEMA_DIR", str(data_dir / "gschemas"))

    # Import and run the original application
    # This maintains backward compatibility while we refactor
    from gnome_connection_manager import app

    # Call main() which creates Wmain and runs it
    app.main()
    return 0
