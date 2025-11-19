# Justfile for gnome-connection-manager
# Install just: cargo install just
# Or: sudo apt install just

# List available commands
default:
    @just --list

# Run the application in development mode
run:
    uv run python -m gnome_connection_manager

# Format code with ruff
fmt:
    uv run ruff format src/ tests/
    uv run ruff check --fix src/ tests/

# Lint code with ruff
lint:
    uv run ruff check src/ tests/

# Type check with mypy
typecheck:
    uv run mypy src/

# Run tests
test:
    uv run pytest

# Run tests with coverage
test-cov:
    uv run pytest --cov --cov-report=html --cov-report=term

# Run all checks (lint, typecheck, test)
check: lint typecheck test

# Install the package in development mode
install:
    uv pip install -e .

# Build distribution packages
build:
    uv build

# Clean build artifacts
clean:
    rm -rf build/ dist/ .eggs/ *.egg-info
    rm -rf .pytest_cache .coverage htmlcov .mypy_cache .ruff_cache
    find . -type d -name __pycache__ -exec rm -rf {} +
    find . -type f -name '*.pyc' -delete

# Compile translations
translate:
    @for po in lang/*/LC_MESSAGES/*.po; do \
        dir=$$(dirname $$po); \
        name=$$(basename $$po .po); \
        msgfmt -o $$dir/$$name.mo $$po; \
    done
    @echo "Translations compiled"

# Create a development environment
setup:
    uv venv --system-site-packages
    uv sync --extra dev
    @echo "Development environment ready!"
    @echo "Activate with: source .venv/bin/activate"
