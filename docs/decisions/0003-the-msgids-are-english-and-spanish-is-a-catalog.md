---
title: "ADR-0003: The msgids are English, and Spanish is a catalog"
description: "Why GCM's messages are written in English, and why that is what a locale with no catalog needs"
audience:
  - contributors
tags:
  - gcm
  - gcm-dev
  - adr
  - i18n
---

# ADR-0003: The msgids are English, and Spanish is a catalog

## Status

Accepted

## Decision

GCM's source language is English. A message in `src/gnome_connection_manager/app.py` or
`utils/connections.py`, and a text in `data/ui/gnome-connection-manager.glade`, is written
in English, and that text is its msgid. Spanish, the language the original author wrote the
messages in, becomes a catalog like the other seven (#391).

`lang/en_US.po` and its compiled `lang/en/` are removed. With English msgids the catalog
would only map each message to itself.

The change re-keyed every msgid that read otherwise than its English translation. Each
became that translation, exactly as `lang/en_US.po` gave it, bar two typos. Each other
catalog keeps its translation under the new msgid. Where two msgids became one, because the
English one already existed, a catalog keeps one translation, the one reviewed in #359, and
the PR that made the change lists each choice.

## Rationale

A message that no catalog translates shows as its msgid, so the msgid is the text of every
locale GCM has no catalog for. It should be a text those users can read, and English is the
language GCM's newer messages were already written in. The rest of this section is how the
msgid shows, why code is not the answer, and what was rejected.

### Where there is no catalog, the msgid is what shows

gettext gives back the msgid wherever it reads no catalog. GCM has two halves that read one:
Python's `gettext`, behind `_()`, and glibc, which translates the glade file's texts for
GtkBuilder. Python's stops at `C`, and glibc ignores `LANGUAGE` while `LC_MESSAGES` is `C` or
`C.UTF-8`. So under `C`, `C.UTF-8`, with no locale set, and in a language GCM has no catalog
for, both halves show the msgids.

The msgids were mostly Spanish, so those users read Spanish, with English where a newer
message had an English msgid. Measured on 9c8504c under `LANG=C.UTF-8`, the main window,
Preferences and the dialog Add Host opens each drew texts in Spanish, Preferences most of
its labels, and under `LANG=en_US.UTF-8` none did. That is #390, which gives the counts.

### English msgids need no code

The fix that keeps Spanish msgids is a fallback to English. Python's half can take the user's
languages followed by `en`. glibc's cannot, since it ignores `LANGUAGE` under `C`, so GCM
would translate the glade file's texts itself, through Python's `gettext`, before GtkBuilder
reads the file. That is a second way of translating, in code, for a problem the source
language solves.

With English msgids every locale without a catalog shows the source, from both halves, and
GCM has nothing to run for it.

### Rejected

**A fallback to English in code.** Above.

**Leaving the msgids as they were.** The mix is the bug, and it grows with every message
written in English, as the newer ones are.

**Keeping `lang/en_US.po`.** It would map each message to itself: an English reader sees the
msgid either way.

## Consequences

- A locale with no catalog shows English, in the Python messages and the glade file alike.
  `test_gcm_shows_english_where_it_reads_no_catalog` starts GCM with no locale set, and
  under `C.UTF-8` and `en_US.UTF-8`, each with and without `LANGUAGE=nl`, and reads what the
  main window, Preferences and the dialog Add Host opens draw.
- A msgid is the text itself, so rewording an English message re-keys it. The catalogs need
  the new msgid, and `test_every_message_is_translated_in_every_catalog` fails until they
  have it, as `test_no_catalog_keeps_an_entry_nothing_uses` does for the old one.
- No msgid may be Spanish, and `test_no_message_is_spanish` keeps that. It is a heuristic:
  accents, function words and the words the old msgids used. A Spanish word it does not know
  passes, so a review is the rest of it.
- A Spanish user reads `lang/es_ES.po` (#391). Of its messages, 159 are the original
  author's Spanish from the old msgids, corrected, and 180 were written for it. Its
  language `es` serves `es_ES`, `es_MX` and `es_CL` alike, which was measured, so no code
  names a Spanish locale. `test_gcm_shows_spanish_where_it_reads_the_catalog` starts GCM
  under `en_US.UTF-8` with `LANGUAGE=es` and under `es_CL.UTF-8`, and reads what the same
  windows draw.
- Seven catalogs show every message as they did, bar the merges. The PR lists those choices
  with the check that found them.

## Related Issues

- Issue #390: Under the C locale, or a language GCM has no catalog for, GCM shows its Spanish source text
- Issue #391: Add a Spanish catalog, so that Spanish speakers keep a Spanish interface once the msgids are English
- Issue #59: Most UI strings have no catalog entry, so they render as Spanish
- Issue #359: The seven other catalogs leave about 200 messages each untranslated, and show 35 to 39 in Spanish

## Related Documentation

- [AGENTS.md](../../AGENTS.md): translation sources, and the tests that keep the catalogs
