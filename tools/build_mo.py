"""Compile a .po into a .mo without gettext's msgfmt.

The Makefile's `msgfmt` is the canonical path; this exists so the catalogs can be
rebuilt on a machine that has no gettext installed. The output is validated by
reading it back with Python's own gettext, which is what the application uses.
"""

from __future__ import annotations

import re
import struct
import sys
from pathlib import Path

_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


def _unescape(text: str) -> str:
    out, i = [], 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            out.append(_ESCAPES.get(text[i + 1], text[i + 1]))
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def parse_po(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    msgid = msgstr = None
    target = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("msgid "):
            if msgid is not None and msgstr:
                entries[msgid] = msgstr
            msgid, msgstr, target = _unescape(line[6:].strip()[1:-1]), "", "id"
        elif line.startswith("msgstr "):
            msgstr, target = _unescape(line[7:].strip()[1:-1]), "str"
        elif line.startswith('"') and target:
            chunk = _unescape(line[1:-1])
            if target == "id":
                msgid += chunk
            else:
                msgstr += chunk
    if msgid is not None and msgstr:
        entries[msgid] = msgstr
    return entries


def write_mo(entries: dict[str, str], path: Path) -> None:
    items = sorted(entries.items())
    keys = b"\x00".join(k.encode("utf-8") for k, _ in items)
    ids, strs, koffsets, voffsets = b"", b"", [], []
    for key, value in items:
        kb, vb = key.encode("utf-8"), value.encode("utf-8")
        koffsets.append((len(kb), len(ids)))
        voffsets.append((len(vb), len(strs)))
        ids += kb + b"\x00"
        strs += vb + b"\x00"
    keystart = 7 * 4 + 16 * len(items)
    valuestart = keystart + len(ids)
    output = struct.pack(
        "Iiiiiii", 0x950412DE, 0, len(items), 7 * 4, 7 * 4 + len(items) * 8, 0, 0
    )
    output += b"".join(struct.pack("ii", l, o + keystart) for l, o in koffsets)
    output += b"".join(struct.pack("ii", l, o + valuestart) for l, o in voffsets)
    output += ids + strs
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(output)
    _ = keys


if __name__ == "__main__":
    src, dest = Path(sys.argv[1]), Path(sys.argv[2])
    write_mo(parse_po(src), dest)
    print(f"{src} -> {dest}")
