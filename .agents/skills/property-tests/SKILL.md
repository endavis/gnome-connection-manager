---
name: property-tests
description: Use when writing a Hypothesis property-based test, when a test already uses `@given` or Hypothesis `st.` strategies, or when asked to add property test coverage for a function or module. Names the property being asserted (round-trip, idempotence, invariant or oracle) before building a strategy from types, marks the test `@pytest.mark.property`, proves it can fail against deliberately broken code, and pins the counterexample as `@example(...)`. Stops and recommends an example-based test when no property fits.
---

# Property Tests

Write a Hypothesis property test for a function or module: a property named up front, a strategy
built from types, and proof -- against deliberately broken code -- that the test can actually fail.

The function or module to test, and what property to check, come from the user's request or from the
task at hand. If neither says, ask before doing anything else.

A property test that only checks a call does not raise, or that restates the implementation under a
different name, passes forever and finds nothing. This skill keeps the judgment calls that prevent
that explicit, instead of leaving them to be skipped under deadline pressure.

## Instructions

### Step 1: Pick the property

State which of these the test asserts, in one sentence, before writing any code:

- **Round-trip** -- `decode(encode(x)) == x`.
- **Idempotence** -- `f(f(x)) == f(x)`.
- **Invariant** -- a relationship every output must satisfy, whatever the input.
- **Oracle** -- the result agrees with a simpler reference implementation.

**If none of these fit, stop: an example-based test is the better tool.** A property with no name
attached is usually a check that the function runs without raising, which is a different, much
weaker claim.

### Step 2: Build the strategy

Build the input from what it is, not from what to reject: `st.builds`, `st.from_type`, or
`@st.composite` for a shape none of those infer directly. Reach for `assume()` or `.filter()` only
once the type-first strategy does not fit -- both discard whatever generated example does not match,
and enough rejections trip Hypothesis's own `HealthCheck.filter_too_much` rather than widen the
strategy to cover the case.

### Step 3: Write the test

Mark it `@pytest.mark.property` -- the marker `pyproject.toml` registers under
`[tool.pytest.ini_options]`. Put it next to any existing property tests for the module it covers;
this template's own `tests/template/test_properties.py` is a worked example, asserting properties of
the skeleton's `greet` function.

**Leave `deadline` and `max_examples` to the `ci` and `default` profiles in `tests/conftest.py`.** Do
not add a per-test `@settings(...)` for either. CI loads the `ci` profile -- `ci.yml` and, since #877,
`mutation.yml` both set `HYPOTHESIS_PROFILE=ci` -- which drops the deadline entirely, because
per-example wall-clock time on a shared runner measures the runner's warmup, not the property under
test (#736). A per-test override fights that profile instead of relying on it.

**A new test file that imports the package needs one more edit.**

See the "### Which Tests Run" section of `docs/development/ci-cd-testing.md`: `mutmut` runs a fixed
test selection (`pytest_add_cli_args_test_selection` in `[tool.mutmut]`), and a test file that imports
the package but is missing from that list never runs against a mutant --
`tests/test_mutmut_config.py::test_every_test_of_the_package_is_selected` fails until it is added.
Adding tests to a file already in that list needs no change.

### Step 4: Prove it can fail

Break the code under test on purpose -- invert a comparison, drop a branch, whatever makes the named
property false -- and run the test. **Confirm the property fails, read what Hypothesis reports, then
undo the deliberate break, not the file's other changes.** Hypothesis reports a `Failing test case:`
block, one generated keyword argument per line -- read what the installed version actually prints
rather than assuming its shape.

Reverse the specific edit that broke the code, then run `git diff <file>` to confirm only the intended
work remains -- no trace of the deliberate break, and nothing else missing either. The code under test
usually already carries the task's own uncommitted changes, such as the new function the property
covers. **Use `git checkout -- <file>` only when the file had no other uncommitted changes before this
step** -- it discards the whole file, the deliberate break along with any real work alongside it.

A test that nobody has watched fail is a test that might not be testing anything.

### Step 5: Pin the counterexample

Step 4 is a drill against code broken on purpose -- there is no bug there to pin. The case this step
covers is different: at any point while a property test runs against the *real* code, Hypothesis may
report a genuine failing input. That is a bug. **Fix the code first.**

Then add the input from the report as `@example(...)` immediately above `@given(...)`, using the same
keyword arguments `@given` takes -- skip `self` if the test is a method, it isn't a parameter
`@example` accepts. Hypothesis also saves a failing input in a local example database
(`.hypothesis/examples/`, gitignored) and retries it first on the next run -- but only on the machine
and checkout that found it. Pinning it as `@example(...)` makes every run check it: a fresh clone, a
teammate's machine, or CI, none of which ever see that local database.

### Step 6: Validate

```bash
uv run pytest -m property <path>
doit check
```

Run the scoped property tests first for fast feedback, then `doit check` before finishing. Stop at the
first failure and report it. Never edit a test to make it pass.

## Notes

- Write scratch files to `tmp/agents/<agent>/` with the issue number in the name, and delete them when
  the task is done.
