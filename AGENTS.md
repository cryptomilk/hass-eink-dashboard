# AGENTS.md

## Commands

```bash
tox -e test          # run all tests
tox -e test -- tests/test_render.py::TestRenderWeather::test_weather_draws_temperature  # run a single test
tox -e lint          # ruff check
tox -e format        # format check
tox -e typecheck     # ty type checker
```

After making changes, ALWAYS run:
- `tox -e format,lint,typecheck,test` for Python changes
- `pnpm --dir custom_components/eink_dashboard/frontend typecheck && pnpm --dir custom_components/eink_dashboard/frontend test` for TypeScript changes

## Architecture

This is a Home Assistant custom component (`custom_components/eink_dashboard/`)
that renders e-ink dashboard images as PNG bytes using Pillow and exposes them
via an HA image entity and a public HTTP endpoint.

**Key files**:
- `render.py` — rendering engine (PIL-based, grayscale)
- `image.py` — `EinkDashboardImage` (`ImageEntity`), scheduled refresh, ETag tracking
- `http.py` — unauthenticated HTTP view at `/api/eink_dashboard/{entry_id}/image.png` with ETag/304 support
- `store.py` — `EinkDashboardStore`, persists widget list via HA's `Store` (`eink_dashboard.{entry_id}`)
- `config_flow.py` — multi-step config flow: name/dimensions/interval, plus TRMNL webhook management (add/remove named webhook targets)
- `optimize.py` — `optimize_for_eink(img, config)`: optional post-render pipeline (autocontrast, sharpness, contrast, grayscale level quantization)
- `push.py` — `async_push_image(session, url, image_bytes)`: HTTP POST of PNG bytes to a webhook URL
- `const.py` — enums, shared constants, and defaults

**Rendering entry point**: `render_dashboard(widget_list, config) -> bytes` in `render.py`
- `config` is a `DisplayConfig` dict with `width`, `height`, `rotation`, and `states` (HA entity ID → state dict)
- Default display: 758×1024 px, 8-bit grayscale (`"L"` mode)
- Dispatches each widget to its renderer via `_RENDERERS`, optionally rotates, returns PNG bytes

**Widget types** (`WidgetType` in `const.py`): `TEXT`, `SEPARATOR`, `WEATHER`, `SENSOR_ROWS`, `DEVICE_BATTERY`, `STATUS_ICONS`, `WASTE_SCHEDULE`

**Adding a widget type**:
1. Add the new value to `WidgetType` in `const.py`
2. Write a renderer function `render_foo(draw, widget, config) -> None` in `render.py`
3. Register it in the `_RENDERERS` dict
4. Add the widget type to `frontend/src/types/ha.d.ts`
5. Add a `_renderFoo()` method in `frontend/src/eink-dashboard-card.ts` and wire it into `_render()`
6. Add the schema and entry to `WIDGET_TYPES` in `frontend/src/eink-dashboard-editor.ts`

**Redesigning a widget type**:
Do not write code directly. Invoke the three skills in order using the
`Skill` tool — each one must complete before the next is called:
1. `/implement-widget-tests` — write failing tests (TDD red phase)
2. `/implement-widget-python` — implement the PIL renderer (green phase)
3. `/implement-widget-frontend` — canvas preview, TS types, editor schema

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
`COLOR_WHITE=255`, `COLOR_GRAY=120`, `COLOR_LIGHT_GRAY=180`, `PADDING=24`.

**Fonts**: `_load_font(size)` (LRU-cached) loads `fonts/Roboto-Regular.ttf`,
falling back to PIL's built-in default.

**Dual renderers**: Each widget type is rendered in two places that must stay
in sync: `render.py` (PIL, produces the actual PNG) and
`eink-dashboard-card.ts` (`_render*()` methods, canvas preview in the
Lovelace editor). When changing layout, coordinates, or data fields in one,
mirror the change in the other.

**Tests** assert visual correctness by scanning pixel regions for dark/gray
pixels. The helper `_pixel(img, x, y)` reads a grayscale pixel value. Weather
forecast entries must include a `"datetime"` ISO 8601 field so day labels can
be derived without timezone assumptions.

**Test infrastructure**: Tests run without a real Home Assistant installation.
`tests/conftest.py` injects stub modules into `sys.modules` before any import.
All HA selectors (`SelectSelector`, `AreaSelector`, `TextSelector` and their
config/enum companions) are stubbed as pass-through identity functions —
`__call__` returns its argument unchanged. Other key stubs: config/options flow
base classes (return plain dicts), `ImageEntity`, `HomeAssistantView`,
`HomeAssistant` (MagicMock), and `cv.url` (real urlparse-based validation).
When adding new HA imports to production code, add matching stubs in
`tests/conftest.py`.

Home Assistant Core Sources: `./.tmp/core`
Home Assistant Frontend Sources: `./.tmp/frontend`
Home Assistant Trmnl: `./.tmp/trmnl-home-assistant`
Home Assistant Lovelace Mushroom: `./.tmp/lovelace-mushroom`
Home Assistant Lovelace Mini Graph Cards: `./.tmp/mini-graph-card`
Home Assistant Mushroom Strategy Dashboard: `./.tmp/mushroom-strategy`

Kindle OnlineScreensaver sources: `./.tmp/kndl-online-screensaver`
