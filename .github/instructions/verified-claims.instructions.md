---
applyTo: '**'
---

Skill: verified-claims

Self-check before writing a factual claim into an issue, commit, PR or doc:

1. Can I paste the exact command and its output? If not, this is inference —
   say so, or go measure it. Every claim that survived review in the session
   that produced this rule had pasted output; every one that did not, failed.
2. Did an exit code come through a pipe? `$?` is the last command's, not the
   script's. Use `out=$(cmd); code=$?`. This error recurred twice in one
   session, the second time reaching a filed issue and a merged PR (#778).
3. Is the claim about a third-party tool? Ask the installed tool, not its type
   definitions, its docs, or a minified bundle (#753, #757, #762).
4. Am I repeating a claim from an issue or an existing doc? Re-measure before
   restating it as fact — an audit's own figures went stale within five days
   (#749).
5. Is it a count, a size or a percentage? It belongs in a file something
   checks, not in prose (#754).
6. If a claim published earlier turns out wrong, correct it where it was
   published, not only in conversation (#757, #778).

Observed failures: endavis/pyproject-template#778, endavis/pyproject-template#757, endavis/pyproject-template#762
