# Development

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- [pnpm](https://pnpm.io/) (for the frontend)
- `cairosvg` (build-time only, for icon generation)

## Commands

### Python (backend)

```bash
uv run --group test pytest                    # run all tests
uv run --group test pytest tests/test_render.py::TestClass::test_name  # run a single test
uv run --group lint ruff check .              # ruff check
uv run --group format ruff format --check .   # ruff format check
uv run --group typecheck ty check             # ty type checker
uv run --group lint ruff check . && uv run --group format ruff format --check . && uv run --group typecheck ty check && uv run --group test pytest  # run everything
```

### TypeScript (frontend)

```bash
pnpm --dir custom_components/eink_dashboard/frontend typecheck
pnpm --dir custom_components/eink_dashboard/frontend test
```

### Build

```bash
python3 scripts/build_icons.py      # regenerate icon PNGs from SVG (weather + MDI)
bash scripts/build_dist.sh           # build both tar.gz and zip into dist/
bash scripts/build_dist.sh --zip     # zip only (HACS)
bash scripts/build_dist.sh --tarball # tar.gz only
```

## Release

1. Ensure `main` is clean and all CI checks pass.
2. Tag the commit:
   ```bash
   git tag v1.2.3
   git push origin v1.2.3
   ```
3. The release pipeline runs automatically:
   - Validates (lint, format, typecheck, test for Python and frontend)
   - Stamps the version from the tag into `manifest.json`
   - Builds `dist/eink_dashboard-1.2.3.tar.gz` and `dist/eink_dashboard.zip`
   - Creates a GitHub release with both files attached and auto-generated release notes
