# Development Guide

This guide covers the modern Python project structure for Gnome Connection Manager.

## Project Structure

```
gnome-connection-manager/
├── src/gnome_connection_manager/  # Main package
│   ├── __init__.py               # Package initialization
│   ├── __main__.py               # CLI entry point
│   ├── main.py                   # Application launcher
│   ├── app.py                    # Main application (legacy code)
│   ├── ui/                       # UI components
│   └── utils/                    # Utility modules
│       └── urlregex.py          # URL patterns
├── data/                         # Non-code assets
│   ├── ui/                      # Glade UI files
│   ├── scripts/                 # Expect scripts
│   └── style.css                # GTK CSS
├── lang/                         # Translations
├── tests/                        # Test suite
├── pyproject.toml               # Project metadata & config
├── dodo.py                      # Task runner entry point (doit)
└── README.md                    # User documentation
```

## Getting Started

### Prerequisites

1. **System Packages** (required for GTK):
   ```bash
   # Ubuntu/Debian
   sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-vte-2.91 expect

   # Fedora
   sudo dnf install python3-gobject gtk3 vte291 expect
   ```

2. **uv** (Python package manager):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

3. **just** (preferred task runner):
   ```bash
   cargo install just
   # or: sudo apt install just
   ```

> Use the doit tasks for day-to-day development (`doit launch`, `doit check`, etc.).
> When you need to run a command that doesn't have a task, wrap it with `uv run ...`
> so the project environment is used.

### Setup Development Environment

```bash
# Create virtual environment with system site packages (for GTK)
uv venv --system-site-packages

# Install development dependencies
uv sync --extra dev

# Activate environment
source .venv/bin/activate
```

## Development Workflow

### Running the Application

```bash
# Using doit (preferred)
doit launch

# Or directly through uv
uv run python -m gnome_connection_manager
```

### Logging

Logs are emitted via Python's `logging` module. Adjust verbosity by setting `GCM_LOG_LEVEL` before running:

```bash
GCM_LOG_LEVEL=DEBUG uv run python -m gnome_connection_manager
```

### Code Quality

```bash
# Format code
doit format
# or: uv run ruff format src/

# Lint code
doit lint
# or: uv run ruff check src/

# Type check
doit type_check
# or: uv run mypy src/

# Run all checks
doit check
```

### Testing

```bash
# Run tests
doit test
# or: uv run pytest

# Run with coverage
doit coverage
```

Some tests drive real GTK/VTE and open real windows. If `Xvfb` is installed the suite
runs them on a private display of its own, so nothing maps on your desktop or steals
keyboard and pointer focus mid-run:

```bash
sudo apt install xvfb
```

Without it the suite still passes, but those windows appear on your real display. To
force the real display -- which is what you want when measuring against the compositor
GCM actually ships on -- set:

```bash
GCM_TEST_REAL_DISPLAY=1 doit test
```

Note that WSLg exports `GDK_SCALE=2.25` and both `DISPLAY` and `WAYLAND_DISPLAY`. The
private display drops all three: GTK prefers Wayland whenever `WAYLAND_DISPLAY` is set,
and on X11 `GDK_SCALE` is applied rather than absorbed, which would report a 960x540
workarea for a 1920x1080 screen.

### Building

```bash
# Build wheel and sdist
doit build
# or: uv build

# Install locally for testing
doit install
# or: uv pip install -e .
```

## Code Style

This project uses:
- **ruff** for linting and formatting (replaces flake8, isort, black)
- **mypy** for type checking
- **pytest** for testing

Configuration is in `pyproject.toml`.

### GTK-specific Style Notes

- GTK uses camelCase for signals and methods: `on_button_clicked`
- Keep camelCase for GTK callbacks (linter configured to allow this)
- Use snake_case for Python functions
- Type hints are encouraged but optional during migration

## Project Configuration

All configuration lives in `pyproject.toml`:
- Project metadata
- Dependencies
- Tool configurations (ruff, mypy, pytest)
- Entry points

## Migration Status

This project is in the process of modernization:
- ✅ Modern Python project structure (src/ layout)
   - ✅ uv for dependency management
   - ✅ Development tools configured (ruff, mypy, pytest)
   - 🔄 Gradual type hint addition
   - 📋 GTK4 migration (future)
   - ✅ GtkApplication framework (single-instance app + GActions)

## Useful Commands

```bash
# Quick reference
doit list         # List all tasks
doit launch          # Run the app
doit check        # Run all quality checks
doit coverage     # Test with coverage report
just clean        # Remove build artifacts
doit translate    # Compile .po files
```

## Contributing

1. Run `doit check` before committing
2. Add type hints to new code
3. Write tests for new features
4. Update documentation
5. Follow existing GTK patterns

## Resources

- [GTK Documentation](https://docs.gtk.org/gtk3/)
- [PyGObject Guide](https://pygobject.readthedocs.io/)
- [uv Documentation](https://docs.astral.sh/uv/)
- [Ruff Documentation](https://docs.astral.sh/ruff/)
