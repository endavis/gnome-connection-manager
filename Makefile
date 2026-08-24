PKG_NAME=gnome-connection-manager
PKG_DESCRIPTION="Simple tabbed SSH and telnet connection manager for GTK environments"
PKG_VERSION=1.2.2
PKG_MAINTAINER="Renzo Bertuzzi <kuthalu@gmail.com>"
PKG_ARCH=all
PKG_ARCH_RPM=noarch
PKG_DEB=${PKG_NAME}_${PKG_VERSION}_${PKG_ARCH}.deb
PKG_RPM=${PKG_NAME}-${PKG_VERSION}.${PKG_ARCH_RPM}.rpm
TMPINSTALLDIR=/tmp/$(PKG_NAME)-fpm-install
DATADIR=$(TMPINSTALLDIR)/usr/share/$(PKG_NAME)
FPM_OPTS=-s dir -n $(PKG_NAME) -v $(PKG_VERSION) -C $(TMPINSTALLDIR) \
	--maintainer $(PKG_MAINTAINER) \
	--description $(PKG_DESCRIPTION) \
	-a $(PKG_ARCH) --license GPLv3 --category net

.PHONY: all deb rpm install translate clean

all: deb rpm

# Compile .po -> .mo translation files. Same walk as `just translate`, so a new
# locale is one file to add rather than two, and it still works where msgfmt is
# not installed. Fails rather than reporting success over an empty list (#101).
translate:
	@set -e; \
	count=0; \
	for po in lang/*.po; do \
		[ -e "$$po" ] || continue; \
		lang=$$(basename "$$po" .po | cut -d_ -f1); \
		mo="lang/$$lang/LC_MESSAGES/gcm-lang.mo"; \
		mkdir -p "$$(dirname "$$mo")"; \
		if command -v msgfmt >/dev/null 2>&1; then \
			msgfmt -o "$$mo" "$$po"; \
		else \
			python3 tools/build_mo.py "$$po" "$$mo" >/dev/null; \
		fi; \
		count=$$((count + 1)); \
	done; \
	if [ "$$count" -eq 0 ]; then \
		echo "no .po files in lang/ -- nothing was compiled" >&2; \
		exit 1; \
	fi; \
	echo "Translations compiled ($$count)"

# Stage all files into TMPINSTALLDIR
install: translate
	rm -rf $(TMPINSTALLDIR)

	# Install the Python package into staging tree (pyaes provided by system python3-pyaes)
	# DEB_PYTHON_INSTALL_LAYOUT: Debian's pip defaults to /usr/local and ignores
	# --prefix without it, and policy forbids a package installing there.
	DEB_PYTHON_INSTALL_LAYOUT=deb pip3 install --no-deps --prefix=/usr --root=$(TMPINSTALLDIR) .

	# Data files: Glade UI, expect script, icon, stylesheet
	mkdir -p $(DATADIR)/ui
	mkdir -p $(DATADIR)/scripts
	cp data/ui/gnome-connection-manager.glade $(DATADIR)/ui/
	cp data/ui/donate.gif $(DATADIR)/ui/
	cp data/scripts/ssh.expect $(DATADIR)/scripts/
	chmod +x $(DATADIR)/scripts/ssh.expect
	cp data/icon.png $(DATADIR)/
	cp data/style.css $(DATADIR)/

	# Translations
	cp -r lang $(DATADIR)/

	# Desktop integration
	mkdir -p $(TMPINSTALLDIR)/usr/share/applications
	cp gnome-connection-manager.desktop $(TMPINSTALLDIR)/usr/share/applications/

	# App icon for desktop environments
	mkdir -p $(TMPINSTALLDIR)/usr/share/pixmaps
	cp data/icon.png $(TMPINSTALLDIR)/usr/share/pixmaps/$(PKG_NAME).png

# Build the .deb package using fpm
deb: install
	rm -f $(PKG_DEB)
	fpm -t deb -p $(PKG_DEB) $(FPM_OPTS) \
		-d python3 \
		-d python3-gi \
		-d python3-gi-cairo \
		-d gir1.2-gtk-3.0 \
		-d gir1.2-vte-2.91 \
		-d expect \
		-d python3-pyaes \
		--after-install postinst \
		--deb-priority optional \
		usr
	@echo "\033[92mOK: $(PKG_DEB)\033[0m"

# Build the .rpm package using fpm (Fedora/RHEL)
rpm: install
	rm -f $(PKG_RPM)
	fpm -t rpm -p $(PKG_RPM) $(FPM_OPTS) \
		-a $(PKG_ARCH_RPM) \
		-d python3 \
		-d python3-gobject \
		-d expect \
		--after-install postinst \
		usr
	@echo "\033[92mOK: $(PKG_RPM)\033[0m"

clean:
	rm -rf $(TMPINSTALLDIR)
	rm -f $(PKG_DEB) $(PKG_RPM)
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true
