# AGENTS.md

## Commands

```bash
uv run --group test pytest                    # run all tests
uv run --group test pytest tests/test_render.py::TestRenderWeather::test_weather_draws_temperature  # run a single test
uv run --group lint ruff check .              # lint
uv run --group format ruff format --check .   # format check
uv run --group typecheck ty check             # typecheck
uv run --group interrogate interrogate -vv custom_components/eink_dashboard/  # docstring coverage
```

After making changes, ALWAYS run:
- `uv run --group lint ruff check . && uv run --group format ruff format --check . && uv run --group typecheck ty check && uv run --group test pytest` for Python changes
- `pnpm --dir custom_components/eink_dashboard/frontend typecheck && pnpm --dir custom_components/eink_dashboard/frontend test` for TypeScript changes

## Architecture

This is a Home Assistant custom component (`custom_components/eink_dashboard/`)
that renders e-ink dashboard images as PNG bytes and exposes them via an HA
image entity and a public HTTP endpoint.

**Key files**:
- `render.py` — rendering orchestrator and shared helpers (delegates to
  `svg_render.py`; also holds `WidgetMetrics`, `_compute_metrics`,
  `color_to_hex`, `DEFAULT_METRICS`, `_load_font`, and other utilities
  imported lazily by `svg_render.py`)
- `svg_render.py` — SVG rendering pipeline: Jinja2 templates, icon-inlining
  filters, `render_widget_svg()`, `_compose_svg()`, `_svg_to_png()` via
  `resvg_py`, `_color_context()`, and per-widget context builders
  (`_build_*_context()`)
- `image.py` — `EinkDashboardImage` (`ImageEntity`), scheduled refresh, ETag tracking
- `http.py` — unauthenticated HTTP view at `/api/eink_dashboard/{entry_id}/image.png` with ETag/304 support
- `store.py` — `EinkDashboardStore`, persists widget list via HA's `Store` (`eink_dashboard.{entry_id}`)
- `config_flow.py` — multi-step config flow: name/dimensions/interval, plus TRMNL webhook management (add/remove named webhook targets)
- `optimize.py` — `optimize_for_eink(img, config)`: optional post-render pipeline (autocontrast, sharpness, contrast, grayscale level quantization)
- `push.py` — `async_push_image(session, url, image_bytes)`: HTTP POST of PNG bytes to a webhook URL
- `sensor.py` — `EinkDashboardSensor`, exposes dashboard state as an HA sensor entity
- `const.py` — enums, shared constants, and defaults

**MDI icons**: SVG files in `icons/svg/mdi/` are inlined into widget
templates by `_mdi_svg_filter()` in `svg_render.py`.  The upstream
source is the `@mdi/svg` npm package installed in the frontend:
`custom_components/eink_dashboard/frontend/node_modules/.pnpm/@mdi+svg@7.4.47/node_modules/@mdi/svg/svg/`.
When adding new icons, copy the SVG file from that directory.

**Rendering entry point**: `render_dashboard(widget_list, config) -> bytes` in `render.py`
- `config` is a `DisplayConfig` dict with `width`, `height`, `rotation`, and `states` (HA entity ID → state dict)
- Default display: 758×1024 px, 8-bit grayscale (`"L"` mode)
- Dispatches each widget to its SVG context builder via `_SVG_RENDERERS` in
  `svg_render.py`, composes one root SVG, rasterises with `resvg_py`, then
  applies rotation and e-ink optimisation, and returns PNG bytes

**Widget types** (`WidgetType` in `const.py`): `TEXT`, `SEPARATOR`, `WEATHER`, `SENSOR_ROWS`, `DEVICE_BATTERY`, `STATUS_ICONS`, `WASTE_SCHEDULE`

**Adding a widget type**:
1. Add the new value to `WidgetType` in `const.py`
2. Create `templates/foo.svg.j2` (may import `_macros.svg.j2` helpers)
3. Write `_build_foo_context(widget, config) -> dict` in `svg_render.py`
4. Register it in `_SVG_RENDERERS` in `svg_render.py`
5. Add the widget type to `frontend/src/types/ha.d.ts`
6. Add the schema and entry to `WIDGET_TYPES` in `frontend/src/eink-dashboard-editor.ts`

**Converting or redesigning a widget type** (PIL→SVG migration or new
widget):
Do not write code directly. Invoke the three skills in order using the
`Skill` tool — each one must complete before the next is called:
1. `/implement-widget-tests` — write failing tests (TDD red phase)
2. `/implement-widget` — implement the SVG template and Python
   context builder (green phase)
3. `/implement-widget-frontend` — TS types and editor schema

**Line length**: 79 characters. Long comments must be wrapped across multiple
lines — never shortened to fit. Split at word boundaries so each line stays
under the limit. Do not abbreviate words or remove meaning to fit on one line.

**Documentation conventions**:
- All functions get a docstring. Small, trivial helpers may use a single
  summary line. Anything with non-obvious behaviour, multiple parameters, or
  a return value gets a full docstring: summary line, description paragraph,
  and all parameters and return values documented. Python uses Google-style
  (`Args:`, `Returns:`); TypeScript uses JSDoc (`@param`, `@returns`).
- Add an inline comment when the WHY is non-obvious: a hidden constraint, a
  loop's non-obvious exit condition, a state-machine transition, a workaround
  for a specific quirk, or geometry/centering math where the formula is not
  self-evident from the variable names.
- Section headers that name a logical group of steps are encouraged, even when
  they describe what the group does — they help readers scan the function
  structure. Avoid per-line narration that merely restates what an individual
  statement does.
- Each test function must have a short comment at the top of the function
  body explaining what the test is verifying.

**Colors**: Integers 0–255. Constants in `const.py`: `COLOR_BLACK=0`,
`COLOR_WHITE=255`, `COLOR_GRAY=120`, `COLOR_LIGHT_GRAY=180`, `PADDING=24`,
`DEFAULT_ROW_H=56`, `DEFAULT_CARD_STYLE="none"`.
`FONT_SIZE_WEATHER=32` (scale denominator for weather geometry; all
other per-widget font-size constants removed in Step 1.7). Use
`color_to_hex(c)` in `render.py` to
convert an integer constant to an SVG hex string (e.g. `COLOR_GRAY` →
`"#787878"`); spread `_color_context()` from `svg_render.py` into context
dicts so templates receive `hex_black`, `hex_white`, `hex_gray` variables
instead of hardcoded literals. `DEFAULT_METRICS = _compute_metrics(
DEFAULT_ROW_H)` in `render.py` is the frozen `WidgetMetrics` instance for
the standard row height; use its fields (`icon_dia`, `icon_inner`,
`font_primary`, etc.) rather than deriving sizes inline.

**Fonts**: `_load_font(size, medium=False)` (LRU-cached) loads
`fonts/Roboto/Roboto-Regular.ttf` (or `Roboto-Medium.ttf` when
`medium=True`),
falling back to PIL's built-in default.

**Rendering**: Widget SVGs are rendered server-side by `svg_render.py`
and fetched by the Lovelace card via the `eink_dashboard/render_widgets`
WebSocket command. There is no client-side canvas renderer. When
changing layout, data fields, or coordinates, only `svg_render.py` and
the Jinja2 templates need updating.

**Tests** assert visual correctness by scanning pixel regions for dark/gray
pixels. Helpers in `tests/helpers.py`: `pixel(img, x, y)` reads a grayscale
pixel value, `content_bbox(img)` finds the tight bounding box of non-white
pixels, `assert_has_dark_pixels()` / `assert_all_white()` /
`assert_has_gray_pixels()` check regions, `assert_vertically_centered()`
and `assert_scales_proportionally()` verify layout geometry,
`make_config()` builds config dicts, `png_to_image()` converts PNG bytes
to a PIL Image. Weather forecast entries must include a `"datetime"` ISO
8601 field so day labels can be derived without timezone assumptions.

**Test infrastructure**: Tests run without a real Home Assistant installation.
`tests/conftest.py` injects stub modules into `sys.modules` before any import.
All HA selectors (`SelectSelector`, `AreaSelector`, `TextSelector` and their
config/enum companions) are stubbed as pass-through identity functions —
`__call__` returns its argument unchanged. Other key stubs: config/options flow
base classes (return plain dicts), `ImageEntity`, `HomeAssistantView`,
`HomeAssistant` (MagicMock), and `cv.url` (real urlparse-based validation).
When adding new HA imports to production code, add matching stubs in
`tests/conftest.py`.

**Commit and PR hygiene**:
- **One concern per PR.** A config-flow UX change and a new widget type
  are two PRs, not one. If a PR touches unrelated areas it is too big to
  review.
- **No fix-then-fix-again chains.** Do not commit code that you then
  correct or rewrite in a later commit in the same PR. Validate the
  approach (run tests, check the dependency is right, verify the
  rendering) *before* committing. If a mistake slips through, amend or
  squash — the reviewer should never see a commit that only exists to
  fix a previous commit in the same PR.
- **Squash iterative polish.** Moving a label, tweaking wording, and
  adjusting alignment on the same feature are one commit, not three.
  Interactive-rebase before opening the PR.
- **Each commit must stand on its own.** Tests pass, lint passes, no
  half-finished code. A reviewer should be able to check out any single
  commit and get a working tree.

Home Assistant Core Sources: `./.tmp/core/`
Home Assistant Frontend Sources: `./.tmp/frontend/`
