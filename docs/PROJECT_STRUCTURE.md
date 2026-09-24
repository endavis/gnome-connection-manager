---
title: "Gnome Connection Manager - Modern Project Structure"
description: "What lives where, and where the modernization work stands"
audience:
  - contributors
tags:
  - gcm
  - gcm-dev
  - development
  - structure
---

# Gnome Connection Manager - Modern Project Structure

## ✅ Completed Setup

### Project Layout
```
gnome-connection-manager/
├── pyproject.toml          # Modern Python project configuration
├── .python-version         # Pin Python version (3.12.3)
├── .gitignore             # Comprehensive Python gitignore
├── dodo.py                # Task runner entry point (doit)
├── DEVELOPING.md          # Developer guide
├── src/
│   └── gnome_connection_manager/
│       ├── __init__.py           # Package root
│       ├── __main__.py           # Entry point
│       ├── main.py               # Application launcher
│       ├── app.py                # Main application code
│       ├── ui/                   # UI components (future)
│       └── utils/
│           └── urlregex.py
├── data/                  # Non-Python assets
│   ├── ui/
│   │   └── gnome-connection-manager.glade
│   ├── scripts/
│   │   └── ssh.expect
│   ├── style.css
│   └── icon.png
└── lang/                  # Translations
```

### Tools & Configuration

**Package Manager:** uv (modern, fast Python package manager)
- Virtual environment with `--system-site-packages` for GTK
- Development dependencies: ruff, mypy, pytest

**Code Quality:**
- `ruff` - Linting & formatting (replaces black, flake8, isort)
- `mypy` - Type checking
- `pytest` - Testing framework

**Entry Points:**
- `gnome-connection-manager` - Main command
- `gcm` - Short alias
- `python -m gnome_connection_manager` - Module execution

### Quick Start

```bash
# Create environment
uv venv --system-site-packages
uv sync --extra dev

# Run application
uv run python -m gnome_connection_manager

# Development tasks (doit)
doit launch    # Run the app
doit check     # Lint, typecheck, test
doit format    # Format code
```

### What's Next?

#### Phase 1: Refactor - Code Quality ✅ COMPLETE
- [x] Modern Python project structure
- [x] uv dependency management
- [x] Fix imports in app.py
- [x] Add basic type hints (15+ key functions)
- [x] Run ruff auto-fixes and formatting
- [x] Fix undefined-name errors (107 fixed)
- [x] Fix None comparisons (51 fixed: `== None` → `is None`)
- [x] Modernize string formatting (88 fixed: `%s` → f-strings)
- [x] Fix type comparisons (9 fixed: `type()` → `isinstance()`)
- [x] Fix bare except clauses (26 fixed - added specific exception types)
- [x] Fix import locations (13 fixed - moved imports to top)
- [x] Pathlib conversions for os.path.join (9 fixed - `os.path.join` → pathlib)
- [x] Clean up unused variables (6 fixed)
- [x] Fix Gdk version requirement warning
- [x] Additional pathlib conversions (13 fixed - os.path.exists, os.makedirs, etc.)
- [x] Code simplifications (13 fixed - ternary operators, context managers, etc.)
- [x] Bugbear issues (5 fixed - lambda bindings, unused variables, etc.)

**Progress:** complete. `ruff check src/ tests/ tools/` reports nothing, and `doit check`
enforces that along with the formatter, so the figures that used to be quoted here are kept
by the gate rather than by this page.

#### Phase 2: Modernize (Future)
- [x] Convert to GtkApplication framework (single-instance `GcmApplication` with action handling)
- [x] Replace SimpleGladeApp with direct GtkBuilder (`GladeComponent` helper inside `app.py`)
- [x] Add GAction/GMenu system (application/menubar exported through `Gio.Menu`)
- [x] Proper logging instead of prints (structured logging via `logging`, configurable with `GCM_LOG_LEVEL`)
- [x] Add comprehensive test suite (`doit test`; `tests/conftest.py` stubs `gi`, and the
      tests that need a real toolkit drive GTK and VTE under their own Xvfb)

#### Phase 3: GTK4 (Long-term)
- [ ] Port to GTK4
- [ ] Menu → PopoverMenu
- [ ] Add Libadwaita
- [ ] Modern UI patterns

### System Requirements

**GTK Dependencies (must be installed via system packages):**
```bash
# Ubuntu/Debian
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-vte-2.91 expect

# Fedora
sudo dnf install python3-gobject gtk3 vte291 expect
```

**Python:** 3.8+ (3.12.3 recommended)

### Benefits of New Structure

1. **Standard Python layout** - src/ layout prevents import issues
2. **Modern tooling** - uv is 10-100x faster than pip
3. **Type safety** - mypy for gradual typing
4. **Code quality** - ruff for fast linting/formatting
5. **Proper packaging** - Can publish to PyPI
6. **Development workflow** - doit tasks for common operations
7. **Reproducible** - .python-version pins Python version

### Migration Notes

- Old `gnome_connection_manager.py` → `src/gnome_connection_manager/app.py`
- Utilities moved to `src/gnome_connection_manager/utils/`
- Data files moved to `data/`
- Entry points configured in `pyproject.toml`
- Import paths need updating in app.py (next step)

### Remaining Code Quality Issues

Both are deliberate, and `pyproject.toml` records the exemption rather than this page:
- [ ] N801: Class name `conf` - Used extensively throughout codebase, requires widespread refactoring
- [ ] SIM115: One file operation without context manager - Intentional design for logging (file must remain open)

Both are intentionally deferred: `conf` is used throughout, so renaming it is a wide
refactor for no behaviour change, and the logging file has to outlive the `with` block that
would close it.

**For Future Phases:**
- [ ] Rename modules to follow Python naming conventions (Phase 2)
- [ ] GTK deprecation warnings (will be addressed in GTK4 migration - Phase 3)
- [ ] Complete type hint coverage (Ongoing)

---

**Status:** Phase 1 is complete and Phase 2 is most of the way there — the application
framework, the menus, logging and the test suite are all in. What is left of Phase 2 is the
module renaming; Phase 3, the GTK4 port, has not started. The lint and formatting gates are
enforced by `doit check` rather than tracked here, because a number written into prose goes
stale and this page's did.
