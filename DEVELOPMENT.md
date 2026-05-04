# Development

## Prerequisites

- Python 3.13+
- [tox](https://tox.wiki/)
- [pnpm](https://pnpm.io/) (for the frontend)
- `cairosvg` (build-time only, for icon generation)

## Commands

### Python (backend)

```bash
tox -e test                    # run all tests
tox -e test -- tests/test_render.py::TestClass::test_name  # run a single test
tox -e lint                    # ruff check
tox -e format                  # ruff format check
tox -e typecheck               # ty type checker
tox -e format,lint,typecheck,test  # run everything
```

### TypeScript (frontend)

```bash
pnpm --dir custom_components/eink_dashboard/frontend typecheck
pnpm --dir custom_components/eink_dashboard/frontend test
```

### Build

```bash
python3 scripts/build_icons.py # regenerate weather icon PNGs from SVG
bash scripts/build_dist.sh     # build distributable tar.gz into dist/
```
