# Contributing to Socksicle

Thanks for helping improve Socksicle! This guide covers how to run the test
suite and what to keep in mind when opening a pull request.

## Getting started

1. Fork the repository and clone it locally.
2. Create a branch for your change (`git checkout -b feat/your-change`).

## Local setup

Socksicle requires Python 3.10+ and Qt (PySide6). Install the runtime
dependencies plus the dev tooling:

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows
# source .venv/bin/activate   # Linux/macOS
pip install -e ".[dev]"
```

## Running the tests

```bash
python -m pytest tests/ -v
```

The GUI tests run with the offscreen Qt platform
(`QT_QPA_PLATFORM=offscreen`), so no display is needed. All network and
subprocess activity is mocked — the suite never downloads or installs
anything.

Options:

```bash
python -m pytest tests/                             # quiet, summary only
python -m pytest tests/test_engines.py -v           # single test module
python -m pytest tests/ --cov=utils --cov-report=term-missing  # coverage
```

## Code style

- Follow the existing style: stdlib-first, no new runtime dependencies
  unless justified, Python type hints where practical.
- Use `logging` (`log = logging.getLogger("...")`) instead of `print()`.
- Catch specific exceptions (`except Exception:`), never bare `except:`.
- Ports are `int`s; keep `local_port` an `int` throughout.

## CI

GitHub Actions runs `python -m pytest tests/ -v` on every push and pull
request (see `.github/workflows/test.yml`). A pull request must pass CI
before it can be merged.

## Opening a pull request

- Write a concise PR title and describe what changed and why.
- Keep the PR focused on one concern; split unrelated changes.
- Mention any behavioural changes in the description (e.g. string ports
  became integers).
- If you change engine provisioning or connection logic, explain how you
  verified it.
- Wait for the CI checks to pass before requesting a review.