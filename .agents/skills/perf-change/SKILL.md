---
name: perf-change
description: Use when optimizing performance-sensitive code, when asked to make something faster, or before claiming a speedup for a change. Takes a measured baseline with `doit benchmark_save`, profiles with the standard library's cProfile to find where the time goes, makes the change, then compares with `doit benchmark_compare` and pastes the table into the PR. Requires a benchmark for the changed path in `tests/benchmarks/` before optimizing it, and `doit check` to pass, since a faster wrong answer is a regression.
---

# Perf Change

Change performance-sensitive code with a measured baseline, a profile, and a pasted comparison —
never a speedup claimed from reading the code.

The function or path to make faster, and why (what's slow, or where it came from: a profile, a user
report, a benchmark trend), come from the user's request or the task that needs it. If neither says,
ask what needs to be faster and why before doing anything else.

This project ships `tests/benchmarks/`, `doit benchmark`, `doit benchmark_save`, `doit
benchmark_compare`, and a benchmark-tracking CI workflow — none of it measures anything unless you run
it, in the order that keeps a claimed speedup honest. The `verified-claims` skill exists to stop
exactly the failure this skill is for: an agent reporting a speedup it never measured.

## Instructions

### Step 1: Confirm a benchmark covers the change

Look in `tests/benchmarks/` for a benchmark that already exercises the function or path you are about
to change.

**If `tests/benchmarks/` has no benchmark for the path being changed, write one before optimizing it.**
Follow the pattern in `tests/benchmarks/test_bench_core.py`:

```python
@pytest.mark.benchmark
def test_bench_<name>(benchmark: Any) -> None:
    """Benchmark <target> with <case>."""
    benchmark(<callable>, *args)
```

New benchmark files belong in `tests/benchmarks/`. Benchmarks are marked `benchmark` and disabled by
default (`--benchmark-disable` in `pyproject.toml`'s `addopts`; see `tests/benchmarks/conftest.py`),
and `tests/test_mutmut_config.py` leaves that directory out of mutation testing on purpose — they time
the package and assert nothing, so they cannot kill a mutant.

Run `doit benchmark` once to confirm the benchmark collects and passes before you rely on it.

### Step 2: Baseline

Before changing anything:

```bash
doit benchmark_save
```

This saves a numbered run under `tmp/benchmarks/` — see `tools/doit/benchmark.py` for the exact
command. `doit benchmark_compare` always diffs against the most recently saved run, so do this
immediately before your change: the newest file has to be the baseline, not something left over from
an earlier session.

### Step 3: Profile

Find out where the time actually goes, with the standard library's `cProfile`, and read the sorted
output with `pstats`:

```bash
mkdir -p tmp/agents/<agent>
uv run python -m cProfile -o tmp/agents/<agent>/perf-<n>-profile.stats \
  -m pytest tests/benchmarks/<file>.py --benchmark-enable --benchmark-only -q -p no:randomly
uv run python -c "import pstats; pstats.Stats('tmp/agents/<agent>/perf-<n>-profile.stats').sort_stats('tottime').print_stats(20)"
rm tmp/agents/<agent>/perf-<n>-profile.stats
```

Sort by `tottime` (self time), not `cumulative`: cumulative is dominated by pytest's own call stack
(`pluggy`, `_pytest.main`), since the profiler wraps the whole test process, not just the function
under test. `tottime` surfaces the module's own lines.

### Step 4: Change

Make the change Step 3 pointed at. Keep the observable behavior identical — same inputs, same
outputs. A correctness fix found while profiling belongs in its own PR, not folded into this one,
unless it is the bug that made the code slow.

### Step 5: Compare

```bash
doit benchmark_compare
```

Read the printed "Comparing against benchmarks from: ..." line and confirm it names the baseline you
took in Step 2. Paste the whole table into the PR description. **No speedup figure without it.**

If the change made things slower, or no measurable difference, that is the answer — report it, don't
rerun until the number looks better.

### Step 6: Validate and record

```bash
doit check
```

**`doit check` must pass; a faster wrong answer is a regression.** Never edit a test to make it pass.
Stop and report the failure instead.

Carry the comparison table, what Step 3 found, and what Step 4 changed into the PR description; a
reviewer should not have to re-run the benchmark to see whether the change helped. When the task is
done, return to the `implement-issue` run, or commit and open a PR per `.github/CONTRIBUTING.md`.

## Notes

- Runs are noisy on shared hardware. Run `uv run pytest --help` and check the current
  `--benchmark-min-rounds` and `--benchmark-warmup` defaults before tuning either one. The
  project's own settings are flags in `addopts` under `[tool.pytest.ini_options]` in
  `pyproject.toml`: GC off and warmup on for every enabled run. The installed plugin reads only
  command-line flags, never a pyproject table (#879). If a comparison looks noisy, rerun `doit
  benchmark_compare` first; for tighter control, run the pytest command from `tools/doit/benchmark.py`
  directly with `--benchmark-min-rounds=<N>` appended, since the doit tasks themselves take no extra
  flags.
- CI tracks benchmark history separately (`docs/development/ci-cd-testing.md`, "Benchmark Tracking"),
  but only from pushes to `main` (`.github/workflows/benchmark.yml`'s `store` job is gated on
  `github.event_name == 'push'`). A PR gets no benchmark comparison from CI, so this skill's local
  table is the only before/after number the PR carries.
- Write scratch files to `tmp/agents/<agent>/` with the issue number in the name, and delete them when
  the task is done.
