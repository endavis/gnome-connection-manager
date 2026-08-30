---
title: Python Project Coding Standards
description: Guidelines for exceptions, typing, structure, testing, and documentation
audience:
  - contributors
tags:
  - coding-standards
  - python
  - best-practices
---

# Python Project Coding Standards

## Overview

Guidelines for exceptions, typing, structure, testing, and documentation to keep your Python project code consistent and safe.

## Audience and Prerequisites

- **Audience:** Contributors writing or reviewing code
- **Prerequisites:** Python 3.12+, familiarity with the repo layout, access to local tooling (`uv`, `doit`, ruff, pytest)

## When to Use This

- Implementing new features or refactors
- Reviewing PRs for compliance and safety
- Adding tests or updating typing/structure

## Quick Start

- Use typed functions with explicit return types
- Prefer specific exceptions over generic ones
- Run `doit format && doit lint && uv run pytest` before submitting

## Coding Standards

### Exception Handling

- Use specific exceptions first (e.g., `ValueError`, `TypeError`, `FileNotFoundError`)
- Create custom exception classes for domain-specific errors
- Only catch generic `Exception` as a last resort
- Include context in error messages for debugging
- For CLI tools: use proper error reporting for user-facing errors

**Example:**
```python
class ConfigError(Exception):
    """Raised when configuration is invalid."""
    pass

def load_config(path: str) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError as exc:
        raise ConfigError(f"Config file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in config: {path}") from exc
```

### Typing

- **Full annotations**: Add type hints to all function parameters and return values
- **Avoid `Any`**: Use specific types; `Any` should be rare and documented
- **Modern syntax**: Use `list[str]`, `dict[str, int]`, `X | None` (Python 3.10+ syntax)
- **Protocols**: Use `typing.Protocol` for structural typing
- **Generic types**: Use `TypeVar` and `Generic` for reusable generic code
- **Override decorator**: Use `@override` (from `typing` in Python 3.12+) on method implementations

**Example:**
```python
from typing import Protocol

class Validator(Protocol):
    """Protocol for validation strategies."""
    def validate(self, data: dict[str, Any]) -> bool: ...

def process_data(
    data: dict[str, Any],
    validator: Validator | None = None
) -> list[str]:
    """Process data with optional validation.

    Args:
        data: Input data to process
        validator: Optional validator instance

    Returns:
        List of processed items
    """
    if validator and not validator.validate(data):
        raise ValueError("Validation failed")
    return [str(v) for v in data.values()]
```

### Project Structure

- **Organization**: Follow consistent package organization
  - `core/`: Core functionality
  - `utils/`: Utility functions
  - `cli/`: Command-line interface
  - `models/`: Data models
- **Public APIs**: Re-export public APIs via `__init__.py` for clean imports
- **Private modules**: Prefix internal modules with `_` (e.g., `_internal.py`)

**Example `__init__.py`:**
```python
"""Public API for myproject."""

from myproject.core.config import Config
from myproject.core.processor import Processor

__all__ = ["Config", "Processor"]
```

### Base Classes and Mixins

- **Inheritance**: Call `super().__init__()` in constructors
- **Mixins**: Use mixins to share common functionality
- **Abstract base classes**: Use `abc.ABC` and `@abstractmethod` for interfaces

**Example:**
```python
from abc import ABC, abstractmethod

class BaseManager(ABC):
    """Base class for all managers."""

    def __init__(self, name: str) -> None:
        self.name = name

    @abstractmethod
    def initialize(self) -> None:
        """Initialize the manager."""
        pass

class ConfigMixin:
    """Mixin for configuration loading."""

    def load_config(self, path: str) -> dict[str, Any]:
        """Load configuration from file."""
        # Implementation here
        pass

class AppManager(BaseManager, ConfigMixin):
    """Application manager with config support."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.config: dict[str, Any] = {}

    def initialize(self) -> None:
        self.config = self.load_config("config.json")
```

### Error Patterns

- **Defensive catches**: Use try-except blocks to prevent crashes in non-critical paths
- **Re-raise**: Re-raise exceptions after logging when appropriate
- **Context preservation**: Use `raise ... from exc` to preserve exception chains
- **Logging**: Log errors with appropriate context before re-raising

**Example:**
```python
import logging

logger = logging.getLogger(__name__)

def safe_operation(data: dict[str, Any]) -> bool:
    """Perform operation with defensive error handling."""
    try:
        process_data(data)
        return True
    except ValueError as exc:
        logger.warning("Validation failed: %s", exc)
        return False
    except Exception as exc:
        logger.error("Unexpected error: %s", exc, exc_info=True)
        raise
```

### Logging

- Use the `logging` module, not `print()` in library code
- Use appropriate log levels (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- Include context in log messages
- Use structured logging when possible

**Example:**
```python
import logging

logger = logging.getLogger(__name__)

def process_file(path: str) -> None:
    logger.info("Processing file: %s", path)
    try:
        # ... processing ...
        logger.debug("File processed successfully: %s", path)
    except Exception as exc:
        logger.error("Failed to process file %s: %s", path, exc, exc_info=True)
        raise
```

## Testing

### Coverage Requirements

- **Minimum coverage target**: ≥70%
- **Commands**: `uv run pytest` or `doit test`
- **Coverage report**: `doit coverage`

### Testing Guidelines

- Add/adjust tests when changing behavior
- Use fixtures for test setup and teardown
- Use mocks/stubs for external dependencies
- Test edge cases and error conditions
- Keep tests focused and independent

**Example:**
```python
import pytest
from myproject.core import Processor

@pytest.fixture
def processor() -> Processor:
    """Create a test processor instance."""
    return Processor(config={"mode": "test"})

def test_processor_success(processor: Processor) -> None:
    """Test successful processing."""
    result = processor.process({"key": "value"})
    assert result == ["value"]

def test_processor_validation_error(processor: Processor) -> None:
    """Test validation error handling."""
    with pytest.raises(ValueError, match="Validation failed"):
        processor.process({})
```

## Documentation

### Docstring Standards

Docstrings are automatically extracted into the [API Reference](https://github.com/endavis/pyproject-template/blob/main/docs/reference/api.md)
using [mkdocstrings](https://mkdocstrings.github.io/).

**Requirements:**

- Use **Google-style docstrings** for consistency
- Document all public functions, classes, and modules
- Include Args, Returns, Raises, Examples sections as appropriate
- Type hints go in signatures, not duplicated in docstrings
- End descriptions with periods for consistency
- Keep line length ≤100 characters

**Example:**
```python
def calculate_score(
    values: list[float],
    weights: list[float] | None = None
) -> float:
    """Calculate weighted score from values.

    Args:
        values: List of numeric values to score
        weights: Optional weights for each value. If None, uses equal weights.

    Returns:
        The calculated weighted score

    Raises:
        ValueError: If values is empty or lengths don't match

    Example:
        >>> calculate_score([1.0, 2.0, 3.0])
        2.0
        >>> calculate_score([1.0, 2.0], weights=[0.3, 0.7])
        1.7
    """
    if not values:
        raise ValueError("values cannot be empty")
    if weights and len(values) != len(weights):
        raise ValueError("values and weights must have same length")

    if weights is None:
        return sum(values) / len(values)
    return sum(v * w for v, w in zip(values, weights))
```

### Comments

- Use inline comments sparingly, only when code intent isn't clear
- Prefer self-documenting code (clear variable/function names)
- Update comments when code changes

### Documentation Maintenance

- Update relevant docs when public behavior changes
- Keep documentation in sync with code
- Use examples to illustrate complex concepts

## Validation and Checks

### Pre-commit Checks

Run these before every commit:

```bash
# Format code
doit format

# Lint code
doit lint

# Type check
doit type_check

# Run tests
uv run pytest
```

### CI/CD Integration

All checks should pass in CI:
- Code formatting (ruff format)
- Linting (ruff check)
- Type checking (mypy)
- Dead code (vulture)
- Test suite (pytest)
- Coverage threshold (pytest-cov)

### Known gate blind spot: unused module-level constants

`doit check` does **not** detect an unused module-level constant whose name begins with an
underscore. Verified against each tool in the stack:

| Tool | Behaviour |
| :--- | :--- |
| vulture | Skips underscore-prefixed names entirely, at any `min_confidence` |
| ruff | `F841` covers unused *locals* only; there is no module-level rule |
| pyright (CLI) | "is not accessed" is an editor-only hint, absent from `--outputjson` |
| mypy | Out of scope by design |

Two independent reasons vulture cannot see it: a leading `_` marks a name as deliberately
private, and even a *public* unused module variable is reported at only 60% confidence — below
the configured `min_confidence = 80`.

Lowering that threshold is not a workable fix: at 60% this repo produces 57 findings, 55 of them
`unused function` for `task_*` and `test_*` names that doit and pytest discover dynamically.

**What this means in practice:** an editor with a Python language server will grey out an unused
private constant, but CI will not fail on it. Treat the "unused symbol" hint as real signal even
though `doit check` is green. See issue #700.

### Import Compatibility

When refactoring imports:
- Update `__init__.py` re-exports
- Verify dependent imports still work
- Consider deprecation warnings for breaking changes

## Code Style

### Ruff Configuration

This template uses Ruff for linting and formatting:

- **Line length**: 100 characters
- **Target version**: Python 3.12+
- **Rules**: See `pyproject.toml` for enabled rule sets
  - E/F: pycodestyle and pyflakes
  - I: isort (import sorting)
  - N: pep8-naming
  - UP: pyupgrade
  - ANN: type annotations
  - B: bugbear
  - C4: comprehensions
  - RUF: Ruff-specific rules

### Example: Good Code Style

```python
"""User management module."""

import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class UserStore(Protocol):
    """Protocol for user storage backends."""

    def get_user(self, user_id: int) -> dict[str, Any] | None: ...
    def save_user(self, user: dict[str, Any]) -> None: ...


class UserManager:
    """Manages user operations with pluggable storage."""

    def __init__(self, store: UserStore) -> None:
        """Initialize manager with storage backend.

        Args:
            store: Storage backend implementing UserStore protocol
        """
        self.store = store
        logger.info("UserManager initialized")

    def create_user(self, name: str, email: str) -> int:
        """Create a new user.

        Args:
            name: User's full name
            email: User's email address

        Returns:
            ID of created user

        Raises:
            ValueError: If email is invalid
        """
        if "@" not in email:
            raise ValueError(f"Invalid email: {email}")

        user = {
            "id": self._generate_id(),
            "name": name,
            "email": email,
        }
        self.store.save_user(user)
        logger.info("Created user: %s", user["id"])
        return user["id"]

    def _generate_id(self) -> int:
        """Generate unique user ID."""
        # Implementation details...
        return 42
```

## Dead Code Detection

### Overview

This template uses [vulture](https://github.com/jendrikseipp/vulture) to detect unused code. Dead code accumulates over time and wastes maintenance effort.

### Running Dead Code Analysis

```bash
# Run dead code detection
doit deadcode
```

### What Vulture Detects

- Unused functions and methods
- Unused variables and attributes
- Unused imports
- Unused classes
- Unreachable code

### Configuration

Vulture is configured in `pyproject.toml` under `[tool.vulture]`:

```toml
[tool.vulture]
min_confidence = 80          # Only report high-confidence findings
paths = ["src", "tests"]     # Directories to scan
ignore_names = ["test_*"]    # Patterns to ignore
ignore_decorators = ["@pytest.fixture"]  # Decorators to ignore
```

### Handling False Positives

Vulture may report false positives for code that's used dynamically. Common examples:

| Pattern | Why It's a False Positive |
|---------|--------------------------|
| Pytest fixtures | Used by name injection |
| Click/Typer commands | Called via decorators |
| `__all__` exports | Used for public API |
| Abstract methods | Implemented in subclasses |
| Logging formatters | Called by logging framework |

**To handle false positives:**

1. **Add to `ignore_names`** in `pyproject.toml`:
   ```toml
   ignore_names = [
       "my_special_function",
       "fixture_*",
   ]
   ```

2. **Add to `ignore_decorators`**:
   ```toml
   ignore_decorators = [
       "@my_framework.command",
   ]
   ```

3. **Use a whitelist file** (for complex cases):
   ```bash
   # Generate whitelist from current findings
   uv run vulture src/ --make-whitelist > vulture_whitelist.py

   # Edit the whitelist to keep only intentional items
   # Then run with whitelist
   uv run vulture src/ vulture_whitelist.py
   ```

### Best Practices

- Run `doit deadcode` periodically during development
- Remove genuinely unused code promptly
- Document why code is kept if it appears unused but is needed
- Keep the confidence threshold at 80+ to avoid noise

## Code Complexity Metrics

### Overview

This template uses [radon](https://radon.readthedocs.io/) to analyze code complexity. Complex code is harder to understand, test, and maintain.

### Running Complexity Analysis

```bash
# Analyze cyclomatic complexity (A-F grades)
doit complexity

# Analyze maintainability index (A-F grades)
doit maintainability
```

### Metrics Explained

#### Cyclomatic Complexity (CC)

Measures the number of independent paths through a function. Lower is better.

| Grade | CC Score | Risk Level |
|-------|----------|------------|
| A | 1-5 | Low - simple, easy to test |
| B | 6-10 | Low - slightly complex |
| C | 11-20 | Moderate - more difficult to test |
| D | 21-30 | High - difficult to test |
| E | 31-40 | Very high - untestable |
| F | 41+ | Extremely high - error-prone |

**Target:** Keep all functions at grade B or better (CC ≤ 10).

#### Maintainability Index (MI)

A composite score based on cyclomatic complexity, lines of code, and Halstead volume. Higher is better.

| Grade | MI Score | Meaning |
|-------|----------|---------|
| A | 20-100 | Highly maintainable |
| B | 10-19 | Moderately maintainable |
| C | 0-9 | Difficult to maintain |

**Target:** Keep all modules at grade A (MI ≥ 20).

### Reducing Complexity

If a function has high complexity:

1. **Extract helper functions** - Break large functions into smaller, focused ones
2. **Use early returns** - Reduce nesting with guard clauses
3. **Simplify conditionals** - Use lookup tables instead of long if-else chains
4. **Apply design patterns** - Strategy pattern can replace complex switches

**Example - Before (CC=8):**
```python
def process(data, mode):
    if mode == "a":
        if data.valid:
            return handle_a(data)
        else:
            return error_a()
    elif mode == "b":
        if data.valid:
            return handle_b(data)
        else:
            return error_b()
    # ... more branches
```

**Example - After (CC=2):**
```python
HANDLERS = {"a": handle_a, "b": handle_b}
ERRORS = {"a": error_a, "b": error_b}

def process(data, mode):
    handler = HANDLERS.get(mode)
    if not handler:
        raise ValueError(f"Unknown mode: {mode}")
    return handler(data) if data.valid else ERRORS[mode]()
```

### Best Practices

- Run `doit complexity` before submitting PRs
- Refactor functions with CC > 10
- Document exceptions where high complexity is justified
- Use maintainability index to identify modules needing attention

## Related Documentation

- [Release Automation](release-and-automation.md)
- [CI/CD Testing](ci-cd-testing.md)
- [Extensions](extensions.md)

## Troubleshooting

### Lint/Format Failures

**Symptom**: Ruff reports violations
**Fix**: Run `doit format && doit lint` and address the violations

### Coverage Drop

**Symptom**: Coverage below threshold
**Fix**: Add/adjust tests for new code paths; use `doit coverage` to see coverage report

### Import Breakage After Refactor

**Symptom**: Imports fail after moving modules
**Fix**: Update `__init__.py` re-exports and verify dependent imports

### Type Checking Errors

**Symptom**: mypy reports type errors
**Fix**: Add proper type annotations; use `# type: ignore[error-code]` sparingly with comments

---

[Back to Documentation Index](../TABLE_OF_CONTENTS.md)
