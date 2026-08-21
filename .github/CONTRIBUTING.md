# Contribution Guide for Aperture

Thank you for your interest in contributing to Aperture!

## Getting Started

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make your changes
4. Run tests: `python3 -m pytest aperture/tests/ -v`
5. Open a Pull Request

## Branch Conventions

| Branch | Purpose |
|---|---|
| `main` | Production-ready code (protected, auto-builds images) |
| `feature/*` | New features |
| `fix/*` | Bug fixes |
| `docs/*` | Documentation updates |

## PR Process

1. All PRs require review from at least one maintainer (@USBKayble)
2. CI must pass (syntax check, lint, unit tests)
3. PRs that modify the image build must be labeled `breaking` if they change
   the system configuration or installed packages
4. Use squash-and-merge to keep history linear

## Issue Templates

- **Bug reports:** Use the `bug_report.md` template
- **Feature requests:** Use the `feature_request.md` template

## Code Style

- Python: PEP 8, 120 char line limit, type hints encouraged
- Shell: Use `set -euo pipefail`
- JSON: 2-space indentation

## Testing

```bash
# Install dev dependencies
pip install pytest pytest-cov flake8

# Run tests
python3 -m pytest aperture/tests/ -v

# Lint
flake8 aperture/src/ --max-line-length=120

# Type check (if mypy is available)
python3 -m mypy aperture/src/ --ignore-missing-imports
```
