PKG_NAME=gnome-connection-manager
PKG_DESCRIPTION="Simple tabbed SSH and telnet connection manager for GTK environments"
PKG_VERSION=1.2.2
PKG_MAINTAINER="Renzo Bertuzzi <kuthulu@gmail.com>"
PKG_ARCH=all
PKG_DEB=${PKG_NAME}_${PKG_VERSION}_${PKG_ARCH}.deb
TMPINSTALLDIR=/tmp/$(PKG_NAME)-fpm-install
DATADIR=$(TMPINSTALLDIR)/usr/share/$(PKG_NAME)
FPM_OPTS=-s dir -n $(PKG_NAME) -v $(PKG_VERSION) -C $(TMPINSTALLDIR) \
	--maintainer $(PKG_MAINTAINER) \
	--description $(PKG_DESCRIPTION) \
	-a $(PKG_ARCH) --license GPLv3 --category net

.PHONY: all deb install translate clean

all: deb

# Compile .po → .mo translation files
translate:
	msgfmt lang/de_DE.po -o lang/de/LC_MESSAGES/gcm-lang.mo
	msgfmt lang/en_US.po -o lang/en/LC_MESSAGES/gcm-lang.mo
	msgfmt lang/fr_FR.po -o lang/fr/LC_MESSAGES/gcm-lang.mo
	msgfmt lang/it_IT.po -o lang/it/LC_MESSAGES/gcm-lang.mo
	msgfmt lang/ko_KO.po -o lang/ko/LC_MESSAGES/gcm-lang.mo
	msgfmt lang/pl_PL.po -o lang/pl/LC_MESSAGES/gcm-lang.mo
	msgfmt lang/pt_BR.po -o lang/pt/LC_MESSAGES/gcm-lang.mo
	msgfmt lang/ru_RU.po -o lang/ru/LC_MESSAGES/gcm-lang.mo

# Stage all files into TMPINSTALLDIR
install: translate
	rm -rf $(TMPINSTALLDIR)

	# Install the Python package into staging tree (pyaes provided by system python3-pyaes)
	pip3 install --no-deps --prefix=/usr --root=$(TMPINSTALLDIR) .

	# Data files: Glade UI, expect script, icon, stylesheet
	mkdir -p $(DATADIR)/ui
	mkdir -p $(DATADIR)/scripts
	cp data/ui/gnome-connection-manager.glade $(DATADIR)/ui/
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

clean:
	rm -rf $(TMPINSTALLDIR)
	rm -f $(PKG_DEB)
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true
