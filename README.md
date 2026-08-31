# Gnome Connection Manager (GCM)

A tabbed SSH and telnet connection manager for GTK 3 desktop environments.

Requires Python 3.12+ and GTK 3.

---

## Documentation

- [Using terminals in GCM](docs/TERMINAL-USAGE.md) - selection when an application
  has taken the mouse, what Copy All copies, pasting, font zoom, and the shortcut table
- [Developing](docs/DEVELOPING.md) and [Project structure](docs/PROJECT_STRUCTURE.md)

## Installation

### From a pre-built .deb

> **Note:** No pre-built packages are available yet. Please build from source using the instructions below.

---

## Building from source

### 1. Install build tools

```bash
sudo apt install git ruby ruby-dev build-essential gettext python3-pip -y
sudo gem install fpm
```

### 2. Clone the repository

```bash
git clone <this repository>

cd gnome-connection-manager
```

### 3. Build the .deb

```bash
make deb
```

This produces `gnome-connection-manager_1.2.2_all.deb` in the current directory.

### 4. Install

```bash
sudo apt install ./gnome-connection-manager_1.2.2_all.deb
```

### Runtime dependencies (resolved automatically by apt)

| Package | Purpose |
|---|---|
| `python3` | Python 3 runtime |
| `python3-gi` | GTK 3 Python bindings |
| `python3-gi-cairo` | Cairo integration |
| `gir1.2-gtk-3.0` | GTK 3 typelib |
| `gir1.2-vte-2.91` | VTE terminal widget |
| `python3-pyaes` | AES encryption for stored passwords |
| `expect` | SSH password injection |

---

## Development setup

GCM uses [uv](https://github.com/astral-sh/uv) for dependency management and [doit](https://pydoit.org/) as a task runner. doit is a dev dependency, so `uv sync` installs it -- there is nothing separate to install.

```bash
# Install uv (modern Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create development environment
uv venv --system-site-packages
uv sync --extra dev

# Prefer doit for day-to-day commands
doit launch   # Launch the app
doit check    # Format, lint, typecheck, tests
doit test     # Run the pytest suite

# Or run directly via uv
uv run python -m gnome_connection_manager
```

**Development status:**
- Phase 1 Code Quality: complete
- Phase 2 Modernization: GTK refactors and logging/tests in progress
- Phase 3 GTK4 Migration: future

See [docs/DEVELOPING.md](docs/DEVELOPING.md) for the full development guide and [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md) for project status.

---

## Running from source (quick start)

```bash
git clone <this repository>
cd gnome-connection-manager
uv venv --system-site-packages
uv sync
doit launch
```

---

## Configuration

GCM stores its configuration in `~/.gcm/gcm.conf`. No manual editing needed.

### Language

GCM uses the system locale by default. To override:

```bash
LANG=en_US.UTF-8 gnome-connection-manager
```

### Logging

```bash
GCM_LOG_LEVEL=DEBUG gnome-connection-manager
```

---

## License

[GPLv3](https://www.gnu.org/licenses/gpl-3.0.html)
