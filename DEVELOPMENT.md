# Development

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- [pnpm](https://pnpm.io/) (for the frontend)
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
bash scripts/build_dist.sh           # build both tar.gz and zip into dist/
bash scripts/build_dist.sh --zip     # zip only (HACS)
bash scripts/build_dist.sh --tarball # tar.gz only
```

## Design Tool

A standalone browser-based preview for developing and debugging widget
templates. Renders a single widget and shows three panels side by side:
raw SVG (inspectable in browser dev tools), resvg-rasterized PNG, and
e-ink-optimized PNG. Runs without a Home Assistant installation.

```bash
uv run --group dev python3 scripts/design_tool.py
```

Open <http://localhost:8088>.

### CLI options

| Flag | Default | Description |
|------|---------|-------------|
| `--widget TYPE` | `weather` | Widget type to preview |
| `--device NAME` | `kindle_pw` | Device preset (display size/grayscale) |
| `--port PORT` | `8088` | HTTP server port |
| `--data FILE` | — | JSON file with widget config and entity states |

### Designing a new widget

The typical workflow for building a new widget from scratch:

1. **Sketch in Inkscape** — create a new SVG document at the target
   display size (e.g. 758×1024). Lay out text, icons, and shapes with
   hardcoded sample values until the visual design looks right.
2. **Convert to a Jinja2 template** — save the SVG as
   `templates/my_widget.svg.j2`. Replace hardcoded values with template
   variables (e.g. `22°C` → `{{ temperature }}°C`), add loops for
   repeated elements, and strip Inkscape metadata.
3. **Add the type** to `WidgetType` in `const.py`.
4. **Create a data file** describing your widget and the entity states
   it needs (see [data file format](#data-file-format) below).
5. **Start the design tool** with your data file:
   ```bash
   uv run --group dev python3 scripts/design_tool.py --data my_widget.json
   ```
6. **Iterate** — edit the `.svg.j2` template (the browser auto-reloads
   on every save) and use the **Data Editor** panel to experiment with
   different entity values without restarting the server. For
   pixel-level tuning, download the SVG from `/svg`, adjust in
   Inkscape, and port the coordinates back.
7. **Wire up the backend** — write `_build_foo_context()` in
   `svg_render.py`, register it in `_SVG_RENDERERS`, and add the
   frontend types and editor schema.

### Iterating on an existing widget

For tweaking an existing widget (layout changes, new fields, bug fixes):

```bash
uv run --group dev python3 scripts/design_tool.py --widget weather
```

The tool loads built-in mock data for all existing widget types. Use the
**Data Editor** panel to adjust entity states (e.g. change temperature,
add forecast entries) and see the effect immediately.

To persist your test data across sessions, click **Download** in the
data editor and restart with `--data`:

```bash
uv run --group dev python3 scripts/design_tool.py --data weather_data.json
```

For pixel-level layout adjustments, right-click the Raw SVG panel →
"Save As…" (or download from `/svg`), open in Inkscape, adjust
positions and sizes visually, then port the coordinates back to the
`.svg.j2` template.

### Live reload

The tool watches `templates/` for `.svg.j2` changes and pushes reload
events via SSE. No manual browser refresh needed. If `--data` is
specified, changes to the data file also trigger a reload.

### Data editor

Expand the **Data Editor** panel below the preview to see the current
widget config and entity states as JSON. Edit values and click **Apply**
to re-render immediately. Click **Download** to save the data as a
`.json` file for reuse with `--data`.

### Data file format

The `--data` flag accepts a JSON file with two keys:

```json
{
  "widget": {
    "type": "weather",
    "entity": "weather.home",
    "x": 24,
    "y": 10,
    "forecast_days": 3
  },
  "states": {
    "weather.home": {
      "state": "sunny",
      "attributes": {
        "temperature": 22,
        "humidity": 45,
        "forecast": [
          {
            "datetime": "2025-01-02T12:00:00",
            "condition": "cloudy",
            "temperature": 18
          }
        ]
      }
    }
  }
}
```

- **widget** — the widget configuration dict (same shape as in a
  dashboard layout).
- **states** — a map of Home Assistant entity IDs to their state
  objects. Each state has a `state` string and an `attributes` dict,
  mirroring the HA state machine format.

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
