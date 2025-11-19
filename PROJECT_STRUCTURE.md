# Gnome Connection Manager - Modern Project Structure

## ✅ Completed Setup

### Project Layout
```
gnome-connection-manager/
├── pyproject.toml          # Modern Python project configuration
├── .python-version         # Pin Python version (3.12.3)
├── .gitignore             # Comprehensive Python gitignore
├── justfile               # Task runner (optional but recommended)
├── DEVELOPING.md          # Developer guide
├── src/
│   └── gnome_connection_manager/
│       ├── __init__.py           # Package root
│       ├── __main__.py           # Entry point
│       ├── main.py               # Application launcher
│       ├── app.py                # Main application code
│       ├── ui/                   # UI components (future)
│       └── utils/
│           ├── SimpleGladeApp.py
│           ├── pyAES.py
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

# Development tasks (with justfile)
just run       # Run the app
just check     # Lint, typecheck, test
just fmt       # Format code
```

### What's Next?

#### Phase 1: Refactor (Current)
- [x] Modern Python project structure
- [x] uv dependency management  
- [ ] Fix imports in app.py
- [ ] Add basic type hints
- [ ] Run ruff to clean up code style

#### Phase 2: Modernize (Future)
- [ ] Convert to GtkApplication framework
- [ ] Replace SimpleGladeApp with direct GtkBuilder
- [ ] Migrate to GSettings from INI files
- [ ] Add GAction/GMenu system
- [ ] Proper logging instead of prints

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
6. **Development workflow** - justfile for common tasks
7. **Reproducible** - .python-version pins Python version

### Migration Notes

- Old `gnome_connection_manager.py` → `src/gnome_connection_manager/app.py`
- Utilities moved to `src/gnome_connection_manager/utils/`
- Data files moved to `data/`
- Entry points configured in `pyproject.toml`
- Import paths need updating in app.py (next step)

### Known Issues

- [ ] app.py still uses old import paths (needs fixing)
- [ ] No tests yet (need to add)
- [ ] Type hints missing (gradual addition)
- [ ] GTK deprecation warnings remain

---

**Status:** ✅ Infrastructure complete, ready for refactoring!
