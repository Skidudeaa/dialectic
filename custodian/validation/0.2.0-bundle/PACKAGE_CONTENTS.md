# Package contents

- `START_HERE.md`: installation, first-run and service handoff.
- `README.md`: complete operation and integration instructions.
- `ARCHITECTURE.md`: the architectural charter and implemented design.
- `custodian/`: all application modules; no compiled-only components.
- `tests/`: the integration and regression test suite.
- `pyproject.toml`: Python packaging metadata and executable entry point.
- `dist/`: the versioned Python wheel built from the enclosed source.
- `examples/custodian.toml`: external policy template with models disabled.
- `VALIDATION.json`: original implementation validation scope and results.
- `TEST_RESULTS.txt`: original output from all 105 passing tests.
- `PACKAGE_VALIDATION.json`: archive and wheel packaging checks for this bundle.
- `SHA256SUMS`: SHA-256 digest for every enclosed file except this checksum list itself.

No credentials, developer private keys, live repository contents, provider billing databases, Git object archives, or installed service definitions are included. Service definitions are generated for your real paths using `custodian service render`.

This package is a source distribution plus a pure-Python wheel, not an operating-system image. Host tools and each target project's dependencies remain external requirements. There are no third-party Python runtime packages to download for Custodian itself.
