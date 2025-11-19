# Gnome Connection Manager or GCM

Gnome Connection Manager or GCM is a tabbed ssh connection manager for gtk+ environments.
Starting with version 1.2.0 it **only** supports python3 and GTK 3 so it should run fine on any modern desktop environment.

If you can't update to python/gtk 3 and only have python2/gtk2, then keep using GCM version v1.1.0 from [kuthulu.com](http://kuthulu.com/gcm/download.html)

## Installation

### From binary package
The easiest way to install GCM is to download the deb or rpm package from [releases](https://github.com/kuthulux/gnome-connection-manager/releases) or from [kuthulu.com](http://kuthulu.com/gcm/download.html) and install it using the package manager

#### Debian/Ubuntu
`sudo dpkg -i gnome-connection-manager_1.2.0_all.deb`

#### Fedora/Redhat
`sudo yum install gnome-connection-manager-1.2.0.noarch.rpm`



### From Sources
Download or clone the repository and execute the file `gnome_connection_manager.py`


```
git clone git://github.com/kuthulux/gnome-connection-manager
cd gnome-connection-manager
./gnome_connection_manager.py
```

#### Dependencies:
* expect
* python3
* python3-gi and gir1.2-vte-2.91 (debian) / python3-gobject (fedora)

### Modern Development Setup (Recommended)

GCM is being modernized with Python best practices and modern tooling. For development:

```bash
# Install uv (modern Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create development environment
uv venv --system-site-packages
uv sync --extra dev

# Run application
uv run python -m gnome_connection_manager
```

**Development Status:**
- ✅ Phase 1 Code Quality: **COMPLETE** (98.7% of issues resolved)
- 📋 Phase 2 Modernization: GTK refactors and logging/tests in progress
- 📋 Phase 3 GTK4 Migration: Future

See [docs/DEVELOPING.md](docs/DEVELOPING.md) for detailed development guide and [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md) for project status.

---

## Logging

GCM writes logs to stderr using Python's logging module. Adjust verbosity by setting `GCM_LOG_LEVEL` (for example `DEBUG`, `INFO`, or `WARNING`) before launching the app:

```bash
GCM_LOG_LEVEL=DEBUG uv run python -m gnome_connection_manager
```

---

## Language
GCM should use the default OS language, but if for any reason you want to use another language, then start GCM this way:

```bash
LANG=en_US.UTF.8 ./gnome_connection_manager.py
```
replace en_US.UTF-8 with the language of your choice.

---

## Packaging

To create a deb or rpm package from source you have to follow these steps:

1. install basic tools

Debian/Ubuntu
```
sudo apt install git ruby ruby-dev build-essential gettext
sudo gem install fpm
```
Fedora/Redhat
```bash
sudo yum install git ruby ruby-devel make gcc gcc-c++ redhat-rpm-config getext rpm-build
sudo gem install fpm
```

2. download or clone the respository

```bash
git clone git://github.com/kuthulux/gnome-connection-manager
cd gnome-connection-manager
```

3. make the desired package:
```bash
#make deb and rpm
make

#make deb package only
make deb

#make rpm package only
make rpm
```

## Contributing
Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.


## License
[GPLv3](https://www.gnu.org/licenses/gpl-3.0.html)
