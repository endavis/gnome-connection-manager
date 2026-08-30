---
title: Optional Extensions
description: Additional tools and extensions for testing, security, and more
audience:
  - contributors
tags:
  - extensions
  - tooling
  - configuration
---

# Optional Extensions

This guide covers optional tools and extensions that you can add to your project based on your specific needs.

## Testing Extensions

### pytest-watch - Auto-run tests on file changes

Automatically run tests when files change, perfect for TDD workflow.

```bash
# Add to pyproject.toml
[project.optional-dependencies]
dev = [
    # ... existing deps ...
    "pytest-watch>=4.2",
]

# Install
uv sync

# Usage
uv run ptw
```

### hypothesis - Property-based testing

Generate test cases automatically based on property specifications.

```bash
# Add to pyproject.toml
[project.optional-dependencies]
dev = [
    # ... existing deps ...
    "hypothesis>=6.0",
]

# Install
uv sync
```

Example test:

```python
from hypothesis import given
from hypothesis import strategies as st

@given(st.integers(), st.integers())
def test_addition_commutative(a, b):
    assert a + b == b + a
```

### faker - Generate realistic fake data

Create realistic test data for your tests.

```bash
# Add to pyproject.toml
[project.optional-dependencies]
dev = [
    # ... existing deps ...
    "faker>=20.0",
]

# Install
uv sync
```

Example usage:

```python
from faker import Faker

fake = Faker()
email = fake.email()
name = fake.name()
address = fake.address()
```

### factory-boy - Test fixtures/factories

Build complex test objects with minimal boilerplate.

```bash
# Add to pyproject.toml
[project.optional-dependencies]
dev = [
    # ... existing deps ...
    "factory-boy>=3.3",
]

# Install
uv sync
```

Example:

```python
import factory

class UserFactory(factory.Factory):
    class Meta:
        model = User

    __GH_OWNER__ = factory.Sequence(lambda n: f"user{n}")
    email = factory.LazyAttribute(lambda obj: f"{obj.__GH_OWNER__}@example.com")
```

### mutmut - Mutation testing

Test your tests by introducing bugs and verifying they catch them.

```bash
# Add to pyproject.toml
[project.optional-dependencies]
dev = [
    # ... existing deps ...
    "mutmut>=3.0",
]

# Install
uv sync

# Usage
uv run mutmut run
uv run mutmut results
```

### vcrpy - Record and replay HTTP interactions

Record HTTP interactions once and replay them in tests for faster, deterministic testing.

```bash
# Add to pyproject.toml
[project.optional-dependencies]
dev = [
    # ... existing deps ...
    "vcrpy>=5.0",
    "pytest-vcr>=1.0",  # pytest integration
]

# Install
uv sync
```

Example:

```python
import vcr

@vcr.use_cassette('fixtures/vcr_cassettes/api_call.yaml')
def test_api_call():
    response = requests.get('https://api.example.com/data')
    assert response.status_code == 200
```

## Performance & Profiling

### py-spy - Low-overhead sampling profiler

Profile your Python code with minimal performance impact.

```bash
# Install globally (not as project dependency)
pip install py-spy

# Usage
py-spy record -o profile.svg -- python your_script.py
py-spy top -- python your_script.py
```

### memray - Memory profiler

Track memory allocations and find memory leaks.

```bash
# Install
pip install memray

# Usage
memray run your_script.py
memray flamegraph memray-output.bin
```

### scalene - CPU+GPU+memory profiler

Comprehensive profiling showing CPU, GPU, and memory usage.

```bash
# Install
pip install scalene

# Usage
scalene your_script.py
```

### line_profiler - Line-by-line profiling

See exactly which lines are slow.

```bash
# Install
pip install line_profiler

# Usage - add @profile decorator to functions
kernprof -l -v your_script.py
```

### Profiling task automation

Add profiling tasks to `dodo.py`:

```python
def task_profile():
    """Profile the application."""
    return {
        "actions": [
            "uv run py-spy record -o tmp/profile.svg -- python -m __PACKAGE_NAME__",
        ],
        "title": title_with_actions,
    }

def task_profile_memory():
    """Profile memory usage."""
    return {
        "actions": [
            "memray run -o tmp/memray.bin python -m __PACKAGE_NAME__",
            "memray flamegraph tmp/memray.bin -o tmp/memray.html",
        ],
        "title": title_with_actions,
    }
```

## Configuration Management

### pydantic-settings - Type-safe configuration

Load and validate configuration from environment variables.

```bash
# Add to pyproject.toml
dependencies = [
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
]

# Install
uv sync
```

Example:

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    api_key: str
    debug: bool = False
    max_connections: int = 10

    class Config:
        env_file = ".env"

settings = Settings()
```

### dynaconf - Multi-environment configuration

Manage settings across development, staging, and production environments.

```bash
# Add to pyproject.toml
dependencies = [
    "dynaconf>=3.2",
]

# Install
uv sync
```

Example structure:

```
settings/
  ├── settings.toml      # Default settings
  ├── .secrets.toml      # Sensitive data (git-ignored)
  └── development.toml   # Development overrides
```

### python-decouple - Strict separation of settings

Simple, strict separation of settings from code.

```bash
# Add to pyproject.toml
dependencies = [
    "python-decouple>=3.8",
]

# Install
uv sync
```

Example:

```python
from decouple import config

DEBUG = config('DEBUG', default=False, cast=bool)
DATABASE_URL = config('DATABASE_URL')
```

## Logging & Monitoring

### loguru - Simplified logging

Easy-to-use logging with sensible defaults.

```bash
# Add to pyproject.toml
dependencies = [
    "loguru>=0.7",
]

# Install
uv sync
```

Example:

```python
from loguru import logger

logger.add("app.log", rotation="500 MB")
logger.info("Application started")
logger.error("An error occurred")
```

### structlog - Structured logging

Output structured, machine-readable logs.

```bash
# Add to pyproject.toml
dependencies = [
    "structlog>=24.0",
]

# Install
uv sync
```

Example:

```python
import structlog

log = structlog.get_logger()
log.info("user_action", user_id=123, action="login")
```

### Sentry integration - Error tracking

Automatically capture and report errors.

```bash
# Add to pyproject.toml
dependencies = [
    "sentry-sdk>=1.40",
]

# Install
uv sync
```

Example:

```python
import sentry_sdk

sentry_sdk.init(
    dsn="your-dsn-here",
    traces_sample_rate=1.0,
)
```

### OpenTelemetry - Observability

Complete observability with traces, metrics, and logs.

```bash
# Add to pyproject.toml
dependencies = [
    "opentelemetry-api>=1.20",
    "opentelemetry-sdk>=1.20",
]

# Install
uv sync
```

## Dependency Management

### pipdeptree - Visualize dependency tree

See your dependency tree and identify conflicts.

```bash
# Add to pyproject.toml
[project.optional-dependencies]
dev = [
    # ... existing deps ...
    "pipdeptree>=2.13",
]

# Install and use
uv sync
uv run pipdeptree
uv run pipdeptree --reverse  # Show what depends on a package
```

## Building Extensible Applications with Entry Points

Python entry points enable plugin architectures that allow users to extend your package without modifying core code.

### Why Use Entry Points?

Entry points are ideal when you want to:
- Allow third-party plugins to extend your application
- Discover extensions automatically at runtime
- Create a plugin ecosystem around your package
- Keep core code separate from optional functionality

### Basic Pattern

**1. Define Plugin Interface**

Create a protocol or abstract base class that all plugins must implement:

```python
# src/__PACKAGE_NAME__/plugin_interface.py
from typing import Protocol

class PluginInterface(Protocol):
    """Protocol that all plugins must implement."""

    @property
    def name(self) -> str:
        """Plugin name."""
        ...

    @property
    def version(self) -> str:
        """Plugin version."""
        ...

    def execute(self, data: dict) -> dict:
        """Execute plugin logic."""
        ...
```

**2. Create Plugin Discovery**

Load and validate plugins from entry points:

```python
# src/__PACKAGE_NAME__/plugin_loader.py
from importlib.metadata import entry_points
from typing import Dict
from .plugin_interface import PluginInterface

def discover_plugins() -> Dict[str, PluginInterface]:
    """Discover and load all plugins."""
    plugins = {}

    # Find all entry points in '__PACKAGE_NAME__.plugins' group
    eps = entry_points(group='__PACKAGE_NAME__.plugins')

    for ep in eps:
        try:
            # Load the plugin class
            plugin_class = ep.load()

            # Instantiate and validate
            plugin = plugin_class()
            if not isinstance(plugin, PluginInterface):
                print(f"Warning: {ep.name} doesn't implement PluginInterface")
                continue

            plugins[plugin.name] = plugin
            print(f"Loaded plugin: {plugin.name} v{plugin.version}")

        except Exception as e:
            print(f"Failed to load plugin {ep.name}: {e}")
            continue

    return plugins
```

**3. Use Plugins in Your Application**

```python
# src/__PACKAGE_NAME__/main.py
from .plugin_loader import discover_plugins

def main():
    """Main application entry point."""
    plugins = discover_plugins()

    print(f"Found {len(plugins)} plugins")

    for name, plugin in plugins.items():
        print(f"Running plugin: {name}")
        result = plugin.execute({"input": "data"})
        print(f"Result: {result}")
```

**4. Create Built-in Plugins**

Register your own plugins in `pyproject.toml`:

```toml
[project.entry-points."__PACKAGE_NAME__.plugins"]
default = "__PACKAGE_NAME__.plugins.default:DefaultPlugin"
csv_export = "__PACKAGE_NAME__.plugins.csv_export:CSVExportPlugin"
```

**5. Enable Third-Party Plugins**

Users can create their own plugins:

```python
# third-party-plugin/src/myplugin/analytics.py
class AnalyticsPlugin:
    """Custom analytics plugin."""

    @property
    def name(self) -> str:
        return "analytics"

    @property
    def version(self) -> str:
        return "1.0.0"

    def execute(self, data: dict) -> dict:
        # Custom analytics logic
        return {"result": "analyzed", "data": data}
```

And register it in their `pyproject.toml`:

```toml
[project.entry-points."__PACKAGE_NAME__.plugins"]
analytics = "myplugin.analytics:AnalyticsPlugin"
```

When users install both packages:

```bash
pip install __PYPI_NAME__
pip install __PYPI_NAME__-analytics
```

Your application automatically discovers and loads the third-party plugin!

### Advanced: Multiple Plugin Types

For complex systems, you can have different types of plugins with different entry point groups:

**Define plugin types in your pyproject.toml:**

```toml
# Your core package
[project.entry-points."__PACKAGE_NAME__.plugin_types"]
processor = "__PACKAGE_NAME__.plugin_types.processor:ProcessorPluginType"
exporter = "__PACKAGE_NAME__.plugin_types.exporter:ExporterPluginType"

# Register built-in plugins by type
[project.entry-points."__PACKAGE_NAME__.processors"]
csv = "__PACKAGE_NAME__.plugins.csv_processor:CSVProcessor"
json = "__PACKAGE_NAME__.plugins.json_processor:JSONProcessor"

[project.entry-points."__PACKAGE_NAME__.exporters"]
s3 = "__PACKAGE_NAME__.plugins.s3_exporter:S3Exporter"
local = "__PACKAGE_NAME__.plugins.local_exporter:LocalExporter"
```

**Plugin Type Manager:**

```python
# src/__PACKAGE_NAME__/plugin_types/processor.py
from dataclasses import dataclass
from typing import Any, Protocol

class ProcessorProtocol(Protocol):
    """Protocol for processor plugins."""

    def process(self, data: Any) -> Any:
        """Process data."""
        ...

@dataclass
class PluginMetadata:
    """Generic plugin metadata."""
    name: str
    version: str
    plugin_type: str
    implementation: type
    description: str = ""

class ProcessorPluginType:
    """Manages processor plugins."""

    @property
    def entry_point_group(self) -> str:
        return "__PACKAGE_NAME__.processors"

    @property
    def type_name(self) -> str:
        return "processor"

    def load_plugin(self, entry_point) -> PluginMetadata:
        """Load a processor plugin."""
        plugin_class = entry_point.load()

        # Validate it implements the protocol
        if not hasattr(plugin_class, 'process'):
            raise ValueError(f"{entry_point.name} missing 'process' method")

        return PluginMetadata(
            name=entry_point.name,
            version=getattr(plugin_class, '__version__', '0.0.0'),
            plugin_type=self.type_name,
            implementation=plugin_class,
        )
```

**Third-party developers can now create plugins:**

```toml
# third-party-package/pyproject.toml
[project.entry-points."__PACKAGE_NAME__.processors"]
xml = "thirdparty_plugin.xml:XMLProcessor"

[project.entry-points."__PACKAGE_NAME__.exporters"]
ftp = "thirdparty_plugin.ftp:FTPExporter"
```

### Real-World Example: CLI Command Registration

A common use case is auto-registering CLI commands from plugins:

```python
# src/__PACKAGE_NAME__/cli.py
import click
from importlib.metadata import entry_points

@click.group()
def cli():
    """Main CLI application."""
    pass

# Discover and register all plugin commands
for ep in entry_points(group='__PACKAGE_NAME__.cli_plugins'):
    try:
        command = ep.load()
        cli.add_command(command)
    except Exception as e:
        click.echo(f"Failed to load plugin {ep.name}: {e}", err=True)

if __name__ == '__main__':
    cli()
```

Third-party plugins can add commands:

```python
# third-party-plugin/src/myplugin/commands.py
import click

@click.command()
@click.option('--output', help='Output file')
def export(output):
    """Export data to file."""
    click.echo(f"Exporting to {output}")
```

Register in their pyproject.toml:

```toml
[project.entry-points."__PACKAGE_NAME__.cli_plugins"]
export = "myplugin.commands:export"
```

Now the command is automatically available:

```bash
$ package-cli export --output data.csv
Exporting to data.csv
```

### Testing Plugin Systems

**Test plugin discovery:**

```python
# tests/test_plugins.py
from __PACKAGE_NAME__.plugin_loader import discover_plugins

def test_discovers_built_in_plugins():
    plugins = discover_plugins()
    assert 'default' in plugins
    assert 'csv_export' in plugins

def test_plugin_implements_interface():
    plugins = discover_plugins()
    for name, plugin in plugins.items():
        assert hasattr(plugin, 'execute')
        assert hasattr(plugin, 'name')
        assert hasattr(plugin, 'version')
```

**Test plugin execution:**

```python
def test_plugin_execution():
    plugins = discover_plugins()
    plugin = plugins['default']

    result = plugin.execute({'test': 'data'})
    assert 'result' in result
```

### Best Practices

1. **Use Protocols**: Define clear interfaces using `typing.Protocol`
2. **Validate Plugins**: Check plugins implement required methods
3. **Handle Errors**: Gracefully handle plugin loading failures
4. **Document Interface**: Clearly document what plugins must implement
5. **Version Compatibility**: Consider plugin version compatibility
6. **Lazy Loading**: Load plugins only when needed
7. **Provide Examples**: Include example plugin implementation
8. **Test Discovery**: Test that built-in plugins are discovered correctly

### Resources

- [Python Packaging Guide - Entry Points](https://packaging.python.org/en/latest/specifications/entry-points/)
- [Setuptools Entry Points](https://setuptools.pypa.io/en/latest/userguide/entry_point.html)
- [PEP 621 - Storing project metadata in pyproject.toml](https://peps.python.org/pep-0621/)

### Example Plugin Systems in the Wild

- **pytest**: Plugins via `pytest11` entry points
- **setuptools**: Build backends and plugins
- **Flask**: Extensions via entry points
- **Sphinx**: Documentation extensions
- **Pylint**: Custom checkers

## Additional Code Quality Tools

### vulture - Dead code detection

Find unused code in your project.

```bash
# Add to pyproject.toml
[project.optional-dependencies]
dev = [
    # ... existing deps ...
    "vulture>=2.10",
]

# Install and use
uv sync
uv run vulture src/
```

Add to `dodo.py`:

```python
def task_dead_code():
    """Find dead code with vulture."""
    return {
        "actions": ["uv run vulture src/"],
        "title": title_with_actions,
    }
```

### radon - Code complexity metrics

Measure cyclomatic complexity and maintainability.

```bash
# Add to pyproject.toml
[project.optional-dependencies]
dev = [
    # ... existing deps ...
    "radon>=6.0",
]

# Install and use
uv sync
uv run radon cc src/ -a  # Cyclomatic complexity
uv run radon mi src/     # Maintainability index
```

### interrogate - Docstring coverage

Measure documentation coverage.

```bash
# Add to pyproject.toml
[project.optional-dependencies]
dev = [
    # ... existing deps ...
    "interrogate>=1.5",
]

# Install and use
uv sync
uv run interrogate src/
```

Configuration in `pyproject.toml`:

```toml
[tool.interrogate]
ignore-init-method = true
ignore-init-module = false
ignore-magic = true
ignore-semiprivate = false
ignore-private = false
ignore-property-decorators = false
ignore-module = false
fail-under = 80
verbose = 2
```

## Container Support

### Basic Dockerfile

Create a `Dockerfile` for containerized deployment:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install uv
RUN pip install uv

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --no-dev

# Copy application code
COPY src/ ./src/

# Run the application
CMD ["uv", "run", "python", "-m", "__PACKAGE_NAME__"]
```

### Docker Compose for development

Create `docker-compose.yml` for local development:

```yaml
version: '3.8'

services:
  app:
    build: .
    volumes:
      - ./src:/app/src
      - ./tests:/app/tests
    environment:
      - DEBUG=true
    ports:
      - "8000:8000"
```

## Multi-version Testing with tox

Test your package across multiple Python versions.

```bash
# Add to pyproject.toml
[project.optional-dependencies]
dev = [
    # ... existing deps ...
    "tox>=4.0",
]

# Install
uv sync
```

Create `tox.ini`:

```ini
[tox]
envlist = py312,py313

[testenv]
deps =
    pytest>=8.0
    pytest-cov>=5.0
commands =
    pytest {posargs}

[testenv:lint]
deps =
    ruff>=0.5
commands =
    ruff check src/ tests/
```

Usage:

```bash
uv run tox          # Run all environments
uv run tox -e py312 # Run specific environment
uv run tox -e lint  # Run linting
```

## Alternative: nox for testing

More flexible than tox, uses Python for configuration.

```bash
# Add to pyproject.toml
[project.optional-dependencies]
dev = [
    # ... existing deps ...
    "nox>=2023.0",
]

# Install
uv sync
```

Create `noxfile.py`:

```python
import nox

@nox.session(python=["3.12", "3.13"])
def tests(session):
    session.install(".[dev]")
    session.run("pytest")

@nox.session
def lint(session):
    session.install("ruff")
    session.run("ruff", "check", "src/", "tests/")
```

Usage:

```bash
uv run nox          # Run all sessions
uv run nox -s tests # Run specific session
```

## Summary

This template provides a solid foundation with the most commonly needed tools. Add extensions from this guide as your project grows and your needs evolve.

### Quick Reference: When to Add What

- **Testing extensions**: When you have complex test scenarios or want to improve test coverage
- **Profiling tools**: When you identify performance issues and need to optimize
- **Configuration management**: When you need multi-environment support or complex settings
- **Logging/monitoring**: When deploying to production and need observability
- **Containers**: When you need consistent deployment environments
- **Multi-version testing**: When releasing a library that must support multiple Python versions

Remember: Start simple, add complexity only when needed.
