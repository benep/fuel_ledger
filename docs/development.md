# Development

Tests and lint, as in CI:

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements_test.txt ruff   # Scripts/ instead of bin/ on Windows
.venv/bin/python -m pytest
.venv/bin/ruff check && .venv/bin/ruff format --check
```

The engine (`custom_components/fuel_ledger/engine/`) has no Home Assistant imports; its tests in `tests/engine/` run
in a second. The tests in `tests/` set up the integration in a test instance of Home Assistant.

Help pages (MkDocs Material, English with a German translation in `*.de.md` next to each page; diagrams in
`docs/assets/diagrams`, a German copy of each as `*.de.svg`):

```bash
.venv/bin/python -m pip install -r requirements_docs.txt
.venv/bin/python -m mkdocs serve
```

User-facing strings live in `strings.json`, copied to `translations/en.json`, with the German translation in
`translations/de.json`. All three have the same keys; a test checks the actions against `services.yaml`.
