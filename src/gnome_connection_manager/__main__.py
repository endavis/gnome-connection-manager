"""Entry point for gnome-connection-manager."""

import sys


def main() -> int:
    """Main entry point for the application."""
    from gnome_connection_manager.main import run

    return run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
