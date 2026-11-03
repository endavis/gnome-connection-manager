---
title: "Translations and the Spanish Catalog"
description: "Why the msgids are English, what glibc, Python's gettext and GtkBuilder were measured to do, how tests/test_i18n.py reads the catalogs, and the Spanish catalog's style rules"
audience:
  - contributors
tags:
  - gcm
  - gcm-dev
  - design
---

# Translations and the Spanish Catalog

Design notes for GCM's translations: the catalogs under `lang/`, which translate the messages
of `src/gnome_connection_manager/app.py` and `data/ui/gnome-connection-manager.glade`; the
checks in `tests/test_i18n.py`; and the Spanish catalog, `lang/es_ES.po`. They say why each
choice was made, what was measured and with which versions, and what was rejected. The decision that the
msgids are English is
[ADR-0003](../decisions/0003-the-msgids-are-english-and-spanish-is-a-catalog.md). The rules
every change follows stay in `AGENTS.md`, and these notes were moved here from it (#430).

## English msgids

The msgids are English (ADR-0003, #390): a msgid is the text an English reader sees, and
English has no catalog. A locale GCM has no catalog for -- `C`, `C.UTF-8`, a language it
lacks -- shows the msgids, from Python's `gettext` and from glibc, which translates the
glade file's texts, alike, with no fallback code. Measured with glibc 2.39: glibc ignores
`LANGUAGE` while `LC_MESSAGES` is `C` or `C.UTF-8`, and Python's `gettext` stops at `C`,
so under `C.UTF-8` neither half reads a catalog, and the Spanish msgids showed. Python's
half read `LANGUAGE=de` there, so `LANG=C.UTF-8 LANGUAGE=de` mixed the two (#395). Now
`bindtextdomain` installs `NullTranslations` under a `C` or `POSIX` messages locale, and
every window is English; the cost is that `LANGUAGE` picks no language under `C.UTF-8`. Rewording
an English message re-keys it: change the msgid in the code or the glade file and in
every catalog, or its translations are lost, and the entry left behind fails
`test_no_catalog_keeps_an_entry_nothing_uses`. GCM was written in Spanish, and
`lang/es_ES.po` is that Spanish, corrected, with the messages written since (#391).

- `test_no_message_is_spanish` keeps every msgid in use English. It is a heuristic --
  accents, function words and the words the Spanish msgids used -- so a Spanish word it
  does not know passes, and review is the rest of it.
- `test_gcm_shows_english_where_it_reads_no_catalog` starts GCM as it starts itself with
  no locale set, and under `C.UTF-8` and `en_US.UTF-8`, each with and without
  `LANGUAGE=nl`, and reads every text the main window, Preferences and the dialog Add
  Host opens draw.

## The Spanish catalog

The Spanish catalog is `lang/es_ES.po` (#391). Its language is `es`, which `es_ES`,
`es_MX` and `es_CL` all read: measured with GTK drawing the windows under each, an `es_*`
locale with no catalog of its own finds `es`. 159 of its messages are the original
author's Spanish, from the msgids #390 rewrote, and 180 were written in #391; the
catalog's header says so.

### Its words

The older text stands where it is correct Spanish. It changed for orthography
(`Archivo no válido`, `solo` without a tilde), an opening `¿`, sentence case, a GNOME
term where it borrowed English (`búfer`, `registro`, `ratón`, `contraseña`, `activar`),
one word for one concept, and meaning that follows the English msgid. Kept on purpose:
`host`; the author's Latin American `agregar`, `ingrese` and `presione`, where GNOME's
Spain-leaning Spanish says `añadir`, `introduzca` and `pulse`; `fragmento` for a
snippet, as GNOME's `recorte` reads as clippings beside Copy and Paste; `por defecto`,
`Atajo`, `Fuente`, `Limpiar` and `Reiniciar y limpiar`; `Eliminar` for both Remove and
Delete; and `administrador` for a manager, where GNOME's Spanish says `gestor`. `Usted`
for sentences, the infinitive for commands, menu items and checkboxes. A word is checked
against GNOME's Spanish by unpacking Ubuntu's `language-pack-gnome-es-base`
(`apt-get download`, then `dpkg-deb -x`) and reading the catalogs in its
`locale-langpack/es/LC_MESSAGES/*.mo` with `gettext`.

### Placeholders and assembled messages

A positional `{}` keeps the English order: the code fills them in that order, and only a
reader can tell a swapped pair, as the mount messages risk. A message the code builds
from two or three msgids, such as `There are` and `open consoles, exit anyway?`, is read
assembled, not as fragments. The English edge stays: a colon, a trailing space, an
ellipsis. The Backspace and Delete combos keep their tabs and bracketed text.

### Messages spelled alike in both languages

`SAME_IN_SPANISH` in `tests/test_i18n.py` lists the messages spelled alike in both
languages (`Host`, `SSH`, `General` and the rest). `test_no_spanish_message_is_left_in_english`
fails on any other translation that reads as its msgid, bar case and access key, which
every check above passes and which shows English; `test_the_list_of_messages_spelled_alike_in_spanish_is_true`
fails on an entry since translated. A correct Spanish word that equals an English msgid
goes on the list with its reason beside it, not a worse word in its place.

### Questions

A question opens with `¿`, which `test_every_spanish_question_opens_with_an_inverted_mark`
holds the catalog to. The code closes three with ` [name]?`, so their translations open
and do not close: `Delete folder`, `Do you really want to remove host` and `Do you
really want to remove all hosts in group`. `Close console` is a fourth, and is a menu
label too, so it cannot open with one; the question needs a msgid of its own, which
changes `app.py` and every catalog, and is left for a follow-up.

### The scenario that reads the Spanish

`test_gcm_shows_spanish_where_it_reads_the_catalog` starts GCM and reads every text the
main window, Preferences and the host dialog draw, under `LANG=en_US.UTF-8
LANGUAGE=es`, the stand-in #359 measured, and under `LANG=es_CL.UTF-8`, a real Spanish
locale. To measure by hand use either: under `C.UTF-8` glibc ignores `LANGUAGE`. Each
case builds its locale in the test's folder with `localedef --no-archive` and
`LOCPATH`, since a machine may have neither generated and CI fails a skipped test. Both
scenarios leave out GTK's stock buttons, the `gtk-add` and `gtk-delete` of the host
dialog's port forwarding page, whose text is GTK's own catalog's and stays English on a
machine without GTK's Spanish.

## Every message translated

Every message GCM shows is translated in every catalog, and `tests/test_i18n.py` holds
each to it (#359). A message added to the code or the glade comes with its translation
in every catalog. An empty `msgstr` shows the English msgid, which is how each catalog
came to leave about 200 untranslated.

- A translation keeps its msgid's placeholders by name, its underscores, its markup,
  its newlines and its tabs.
- In the menu bar and in the application menu, listed in the test's `MENUS`, each
  label's access key is its own, in every catalog and in English, whose labels are the
  msgids. The menu bar's Hosts is `H_osts`, since `_Help` has H: measured with real input,
  two labels with one key opened their menus by turns (#382). Korean writes a key as
  GNOME's Korean does, `파일(_F)`.
- The test reads `_()` in either quote, since a message inside an f-string takes the
  other quote, `f"{_('Invalid file')}: {e}"`, unless it holds an apostrophe, as
  `_("Can't open file for writing")` does, which Python 3.12 allows in double quotes
  there. It reads a glade text as GtkBuilder looks it up, edge spaces included.
  Measured with a catalog holding both forms of a label that ends in a space,
  GtkBuilder showed the spaced form's translation.
- A catalog keeps no entry that nothing uses, bar `translator-credits`, which names its
  translators.
- A `msgstr` that is its own msgid passes msgfmt and the test alike, and shows English.
  Korean held nine and Polish one, found by asking `gettext` which messages in use come
  back as their msgids.
