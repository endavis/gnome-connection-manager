---
name: dead-code-triage
description: Use when `doit check` or `doit deadcode` reports a vulture finding — an unused import,
  an unused variable (an unused function argument), or unreachable code — and you need to decide
  whether to fix it, add a documented `ignore_names` exception, or ask, rather than deleting or
  whitelisting it by reflex. Checks `[tool.vulture]` in `pyproject.toml` for the configured threshold
  and existing exceptions before touching any code.
---

# Dead Code Triage

Decide what a vulture finding means before deleting code, hiding it, or leaving a bug in place.

The finding comes from the user's request or from `doit check`'s output. If neither says which one,
run `doit deadcode` yourself and triage every finding it reports, one at a time.

`doit check` runs `doit deadcode` as one of its `task_dep` (`tools/doit/quality.py`), so a vulture
finding blocks the check. Deleting the flagged code or adding it to `ignore_names` by reflex is
exactly the failure this skill exists to stop: some findings are real dead code, and some are code
an interface, a framework, or the type checker still needs.

Before Step 1, read `[tool.vulture]` in `pyproject.toml`. It holds `min_confidence`, the `paths`
vulture scans, and `ignore_names`/`ignore_decorators` — the exceptions already agreed on, each with a
comment saying why. It is the configuration this skill applies; where the two disagree, the config
wins and this skill is out of date.

## Instructions

### Step 1: Read the finding

Every vulture line has the same shape: `<file>:<line>: <message> (<confidence>% confidence)`. Note
the file, line, name and message before doing anything else — Step 2 branches on the message.

At this repo's configured `min_confidence`, vulture reports three kinds of finding:

- `unused import '<name>'`
- `unused variable '<name>'` — at this threshold this is always a function argument. A plain unused
  local variable (a loop variable, a `with ... as` or tuple-unpack target, an augmented assignment)
  scores below the threshold and will not reach you here; if `min_confidence` ever drops and one
  does, it is a real unused local — delete it.
- `unreachable code after 'return'` (or another exit statement)

A fourth kind — `unused function`/`class`/`method` — also appears only if `min_confidence` drops.
`ignore_decorators` in the same table already exempts common registration patterns (pytest fixtures,
click commands, `@abstractmethod`); extend it, or add a narrow `ignore_names` entry (Step 3), rather
than inventing a new rule here.

### Step 2: Triage by kind

**Unused import.** Check, in order, before deleting:

1. Is it imported under `if TYPE_CHECKING:` and used only in a string annotation (`x: "Thing"`)?
   Deleting it clears the finding but breaks type checking — the `ConsoleType` entry in
   `ignore_names` documents this exact case.
2. Is it re-exported? A name listed in a literal `__all__ = [...]` and any import inside an
   `__init__.py` are already invisible to vulture. If it is still flagged, the re-export happens some
   other way — built dynamically, or imported somewhere `__all__` does not cover — so trace it before
   deleting.
3. Is it a side-effect import: one that registers something (a plugin, a driver, a route) on import
   and is never referenced by name? Grep for where the side effect is required before deleting.

None of the three apply: delete the import.

**Unused variable, i.e. a function argument.** Vulture cannot see whether a caller or a framework
imposes the signature.

1. Does something outside your control call this with positional or keyword arguments — a base
   class, a framework callback, a registered handler? Keep the parameter.
   - Every caller passes it positionally: prefix it with `_` (`def handler(event, _context)`).
     Vulture reports nothing for the argument itself once it is `_`-prefixed, at any confidence.
   - A caller passes it by name: `_`-prefixing breaks that call. Add a narrow `ignore_names` entry
     instead (Step 3), with a comment naming the interface that requires the name.
2. Nothing imposes the signature: remove the parameter and update every caller.

**Unreachable code.** Check whether the statement before it exits too early before deleting
anything.

1. Does that statement `return`, `raise`, `break`, or `continue` when it should not always do so —
   guarding a branch that should still run the code after it? That is a bug: fix the early exit, not
   the code it hides.
2. The early exit is correct and the code after it is genuinely never reached: delete it.

**Unsure about any of the above:** ask the user rather than guessing. A wrong guess here either
deletes something an interface needs or hides a real bug behind `ignore_names`.

### Step 3: Record the decision

A new `ignore_names` entry always carries a comment naming the reference vulture cannot see — the
same shape as the entries already in `[tool.vulture]`. An entry with no comment is the next reader's
problem: nothing will tell them why it is there.

If Step 2 changed code instead — deleted an import, renamed a parameter and its call sites, removed
dead code, fixed an early exit — the diff is the record; describe what you found and why in the
commit or PR, same as any other fix.

### Step 4: Validate

```bash
doit deadcode
```

Confirm the finding you triaged is gone and no new one appeared, then run `doit check` before
finishing.

## Notes

- One finding can need a code change and a config change together — make both in the same pass, not
  two.
- Write scratch files to `tmp/agents/<agent>/` with the issue number in the name, and delete them
  when the task is done.
