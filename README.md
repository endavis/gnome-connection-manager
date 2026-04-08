# Gnome Connection Manager (GCM)

A tabbed SSH and telnet connection manager for GTK 3 desktop environments.

Requires Python 3.8+ and GTK 3.

---

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

## Running from source (development)

```bash
git clone <this repository>

cd gnome-connection-manager

# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Set up the environment
uv venv --system-site-packages
uv sync

# Run
just run
# or
uv run python -m gnome_connection_manager
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
