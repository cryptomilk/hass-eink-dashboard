#!/usr/bin/env python3
"""Design tool: live-preview e-ink widget templates in a browser.

Renders one or more widget types and serves a three-panel preview
page showing the raw SVG, resvg-rasterized PNG, and e-ink-optimized
PNG.  Watches template and data files for changes and pushes reload
events via Server-Sent Events.

Runs without a Home Assistant installation.

Usage:
    python3 scripts/design_tool.py
    python3 scripts/design_tool.py --widget weather --device trmnl_og
    python3 scripts/design_tool.py --widget heading --port 9000
    python3 scripts/design_tool.py --widget entity --data my_data.json

Omitting ``--widget`` shows a multi-widget dashboard preview
(weather + tile + waste_schedule).
"""

from __future__ import annotations

import argparse
import html
import io
import json
import logging
import re
import subprocess
import sys
import threading
import time
import traceback
from http import HTTPStatus
from http.server import (
    BaseHTTPRequestHandler,
    ThreadingHTTPServer,
)
from pathlib import Path

from _bootstrap import PKG, import_module
from PIL import Image
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

# -------------------------------------------------------------------
# Bootstrap: import eink_dashboard modules without Home Assistant
# -------------------------------------------------------------------
import_module(f"{PKG}.const")
import_module(f"{PKG}.optimize")
import_module(f"{PKG}.conditions")
import_module(f"{PKG}.svg_render")
import_module(f"{PKG}.render")

from bench_render import (
    _MOCK_DATA,
    _build_config,
)

from custom_components.eink_dashboard.const import (
    DEVICE_PRESETS,
    PADDING,
    DevicePreset,
    WidgetType,
)
from custom_components.eink_dashboard.optimize import (
    optimize_for_eink,
)
from custom_components.eink_dashboard.svg_render import (
    _compose_svg,
    _svg_to_png,
    render_widget_svg,
)

# -------------------------------------------------------------------
# Constants and logger
# -------------------------------------------------------------------

_TEMPLATE_DIR = (
    Path(__file__).parent.parent
    / "custom_components"
    / "eink_dashboard"
    / "templates"
)

_FRONTEND_DIR = (
    Path(__file__).parent.parent
    / "custom_components"
    / "eink_dashboard"
    / "frontend"
)

_BRAND_ICON = (
    Path(__file__).parent.parent
    / "custom_components"
    / "eink_dashboard"
    / "brand"
    / "icon.png"
)

_RESIZE_MATH_TS = _FRONTEND_DIR / "src" / "resize-math.ts"
_RESIZE_MATH_JS = _FRONTEND_DIR / "resize-math.js"

_logger = logging.getLogger("design_tool")

# -------------------------------------------------------------------
# Rendering helpers
# -------------------------------------------------------------------


def _render_svg(widgets: list[dict], config: dict) -> str:
    """Render one or more widgets inside a dashboard-sized SVG canvas.

    Produces a full SVG document with a white background and each
    widget positioned at its configured (x, y).

    Args:
        widgets: List of widget configuration dicts.
        config: Display config with width, height, and states.

    Returns:
        SVG document string.
    """
    svg_parts = []
    positions = []
    for widget in widgets:
        svg_parts.append(render_widget_svg(widget, config))
        positions.append((widget.get("x", PADDING), widget.get("y", 0)))
    return _compose_svg(
        svg_parts,
        positions,
        config["width"],
        config["height"],
    )


def _render_png(svg: str, config: dict) -> bytes:
    """Rasterize an SVG document to PNG bytes via resvg.

    Args:
        svg: SVG document string.
        config: Display config with width and height.

    Returns:
        PNG image bytes.
    """
    return _svg_to_png(svg, config["width"], config["height"])


def _render_optimized(png_bytes: bytes, config: dict) -> bytes:
    """Apply e-ink optimization to raw PNG bytes.

    Forces ``optimize=True`` so the third panel always shows
    the post-processed output regardless of device preset.

    Args:
        png_bytes: Raw PNG bytes from ``_render_png``.
        config: Display config with grayscale and enhancement
            parameters.

    Returns:
        Optimized PNG image bytes.
    """
    img = Image.open(io.BytesIO(png_bytes)).convert("L")
    opt_config = {**config, "optimize": True}
    img = optimize_for_eink(img, opt_config)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


# -------------------------------------------------------------------
# HTML template
# -------------------------------------------------------------------

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>E-Ink Dashboard Design Tool</title>
<link rel="icon" type="image/png" href="/favicon.png">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: system-ui, sans-serif;
    background: #2d2d2d;
    color: #e0e0e0;
    padding: 16px;
  }}
  h1 {{ font-size: 18px; margin-bottom: 12px; color: #ccc; }}
  .info {{
    font-size: 13px; color: #999; margin-bottom: 16px;
  }}
  .panels {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 16px;
  }}
  .panel {{
    background: #3a3a3a;
    border-radius: 8px;
    padding: 12px;
  }}
  .panel h2 {{
    font-size: 14px; color: #aaa; margin-bottom: 8px;
    text-transform: uppercase; letter-spacing: 0.5px;
  }}
  .panel .canvas {{
    background:
      repeating-conic-gradient(
        #555 0% 25%, #444 0% 50%
      ) 50% / 20px 20px;
    display: flex;
    justify-content: center;
    padding: 8px;
    border-radius: 4px;
    min-height: 200px;
    position: relative;
  }}
  .panel img, .panel object {{
    max-width: 100%; height: auto;
  }}
  .resize-handle {{
    position: absolute;
    width: 12px; height: 12px;
    background: rgba(3,169,244,0.9);
    border: 1.5px solid #fff;
    border-radius: 2px;
    z-index: 10;
    display: none;
    touch-action: none;
    box-sizing: border-box;
  }}
  .resize-handle::before {{
    content: "";
    position: absolute;
    inset: -8px;
  }}
  .resize-handle[data-handle="nw"],
  .resize-handle[data-handle="se"] {{ cursor: nwse-resize; }}
  .resize-handle[data-handle="ne"],
  .resize-handle[data-handle="sw"] {{ cursor: nesw-resize; }}
  .resize-handle[data-handle="w"],
  .resize-handle[data-handle="e"]  {{ cursor: ew-resize; }}
  #resize-outline {{
    position: absolute;
    border: 2px dashed rgba(3,169,244,0.6);
    display: none;
    pointer-events: none;
    box-sizing: border-box;
  }}
  #error {{
    display: none;
    background: #8b0000; color: #fff;
    padding: 12px; border-radius: 6px;
    margin-bottom: 12px;
    font-family: monospace; font-size: 13px;
    white-space: pre-wrap;
  }}
  .data-editor {{
    margin-top: 16px;
    background: #3a3a3a;
    border-radius: 8px;
  }}
  .data-editor summary {{
    cursor: pointer;
    padding: 12px;
    font-size: 14px; color: #aaa;
    text-transform: uppercase; letter-spacing: 0.5px;
  }}
  .data-editor .editor-body {{
    padding: 0 12px 12px;
  }}
  .data-editor textarea {{
    width: 100%;
    min-height: 300px;
    background: #2d2d2d;
    color: #e0e0e0;
    border: 1px solid #555;
    border-radius: 4px;
    padding: 8px;
    font-family: monospace;
    font-size: 13px;
    resize: vertical;
    tab-size: 2;
  }}
  .data-editor .buttons {{
    margin-top: 8px;
    display: flex;
    gap: 8px;
  }}
  .data-editor button {{
    padding: 6px 16px;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-size: 13px;
  }}
  .data-editor .btn-apply {{
    background: #2e7d32; color: #fff;
  }}
  .data-editor .btn-apply:hover {{ background: #388e3c; }}
  .data-editor .btn-download {{
    background: #555; color: #e0e0e0;
  }}
  .data-editor .btn-download:hover {{ background: #666; }}
  .data-editor .editor-status {{
    font-size: 12px; color: #999;
    margin-left: 8px;
    align-self: center;
  }}
  .status {{
    position: fixed; bottom: 12px; right: 12px;
    padding: 4px 10px; border-radius: 4px;
    font-size: 12px; background: #444;
  }}
  .status.connected {{ background: #2e7d32; }}
  .status.disconnected {{ background: #8b0000; }}
</style>
</head>
<body>
<h1>E-Ink Dashboard Design Tool</h1>
<div class="info">
  Widget: <b>{widget_type}</b> |
  Device: <b>{device_name}</b>
  ({width}&times;{height}, {grayscale_levels}-level) |
  Port: {port}
</div>
<div id="error"></div>
<div class="panels">
  <div class="panel">
    <h2>Raw SVG</h2>
    <div class="canvas" id="svg-canvas">
      <object id="svg-view" data="/svg"
              type="image/svg+xml"
              width="{width}" height="{height}">
      </object>
      <div id="resize-outline"></div>
      <div class="resize-handle" data-handle="nw"></div>
      <div class="resize-handle" data-handle="ne"></div>
      <div class="resize-handle" data-handle="sw"></div>
      <div class="resize-handle" data-handle="se"></div>
      <div class="resize-handle" data-handle="w"></div>
      <div class="resize-handle" data-handle="e"></div>
    </div>
  </div>
  <div class="panel">
    <h2>Rendered PNG</h2>
    <div class="canvas">
      <img id="png-view" src="/png" alt="Rendered PNG">
    </div>
  </div>
  <div class="panel">
    <h2>Optimized PNG (e-ink)</h2>
    <div class="canvas">
      <img id="opt-view" src="/optimized.png"
           alt="Optimized PNG">
    </div>
  </div>
</div>
<details class="data-editor">
  <summary>Data Editor</summary>
  <div class="editor-body">
    <textarea id="data-editor">{initial_data}</textarea>
    <div class="buttons">
      <button class="btn-apply" onclick="applyData()">
        Apply
      </button>
      <button class="btn-download" onclick="downloadData()">
        Download
      </button>
      <span id="editor-status" class="editor-status"></span>
    </div>
  </div>
</details>
<div id="status" class="status disconnected">
  disconnected
</div>
<script>
(function() {{
  var es = new EventSource("/events");
  var status = document.getElementById("status");
  var errDiv = document.getElementById("error");
  es.onopen = function() {{
    status.textContent = "watching";
    status.className = "status connected";
  }};
  es.onerror = function() {{
    status.textContent = "disconnected";
    status.className = "status disconnected";
  }};
  es.onmessage = function(e) {{
    var ts = Date.now();
    if (e.data === "reload") {{
      errDiv.style.display = "none";
      document.getElementById("svg-view").data =
        "/svg?t=" + ts;
      document.getElementById("png-view").src =
        "/png?t=" + ts;
      document.getElementById("opt-view").src =
        "/optimized.png?t=" + ts;
      window.dispatchEvent(new CustomEvent("design-reload"));
    }} else if (e.data.startsWith("error:")) {{
      errDiv.textContent = e.data.substring(6);
      errDiv.style.display = "block";
    }}
  }};
}})();

function applyData() {{
  var ta = document.getElementById("data-editor");
  var es = document.getElementById("editor-status");
  try {{
    JSON.parse(ta.value);
  }} catch (e) {{
    es.textContent = "Invalid JSON: " + e.message;
    es.style.color = "#ff6b6b";
    return;
  }}
  es.textContent = "Applying…";
  es.style.color = "#999";
  fetch("/data", {{
    method: "POST",
    headers: {{"Content-Type": "application/json"}},
    body: ta.value,
  }}).then(function(r) {{
    if (r.ok) {{
      es.textContent = "Applied";
      es.style.color = "#81c784";
      setTimeout(function() {{ es.textContent = ""; }}, 2000);
    }} else {{
      return r.text().then(function(t) {{
        es.textContent = "Error: " + t;
        es.style.color = "#ff6b6b";
      }});
    }}
  }}).catch(function(e) {{
    es.textContent = "Request failed: " + e.message;
    es.style.color = "#ff6b6b";
  }});
}}

function downloadData() {{
  var ta = document.getElementById("data-editor");
  var wtype = "widget";
  try {{
    var d = JSON.parse(ta.value);
    if (d.widget && d.widget.type) wtype = d.widget.type;
    else if (d.widgets && d.widgets.length) wtype = "dashboard";
  }} catch (e) {{ /* use default filename */ }}
  var blob = new Blob([ta.value], {{type: "application/json"}});
  var a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = wtype + "_data.json";
  a.click();
  URL.revokeObjectURL(a.href);
}}
</script>
<script type="module">
import {{
  applyEdgeResize, applyCornerResize, MIN_RESIZE_DIM,
  scaleSvgPreview, clearSvgScale,
}} from "/js/resize-math.js";
const DISPLAY_W = {width};
const DISPLAY_H = {height};
const HANDLE_HALF = 6;
let geom = null;
let resizing = null;
const canvas  = document.getElementById("svg-canvas");
const svgObj  = document.getElementById("svg-view");
const outline = document.getElementById("resize-outline");
const handles = Array.from(
  document.querySelectorAll(".resize-handle")
);
function getScale() {{
  return svgObj.clientWidth / DISPLAY_W;
}}
function objOffset() {{
  var or_ = svgObj.getBoundingClientRect();
  var cr  = canvas.getBoundingClientRect();
  return {{left: or_.left - cr.left, top: or_.top - cr.top}};
}}
function positionHandles() {{
  if (!geom) return;
  var s   = getScale();
  var off = objOffset();
  var gx  = off.left + geom.x * s;
  var gy  = off.top  + geom.y * s;
  var gw  = geom.w * s;
  var gh  = geom.h * s;
  outline.style.left    = gx + "px";
  outline.style.top     = gy + "px";
  outline.style.width   = gw + "px";
  outline.style.height  = gh + "px";
  outline.style.display = "block";
  var pos = {{
    nw: [gx - HANDLE_HALF,      gy - HANDLE_HALF],
    ne: [gx + gw - HANDLE_HALF, gy - HANDLE_HALF],
    sw: [gx - HANDLE_HALF,      gy + gh - HANDLE_HALF],
    se: [gx + gw - HANDLE_HALF, gy + gh - HANDLE_HALF],
    w:  [gx - HANDLE_HALF,      gy + gh / 2 - HANDLE_HALF],
    e:  [gx + gw - HANDLE_HALF, gy + gh / 2 - HANDLE_HALF],
  }};
  handles.forEach(function(h) {{
    var p = pos[h.dataset.handle];
    if (!p) return;
    h.style.left = p[0] + "px";
    h.style.top  = p[1] + "px";
    h.style.display = "block";
  }});
}}
function fetchGeom() {{
  fetch("/geometry")
    .then(function(r) {{ return r.json(); }})
    .then(function(g) {{
      geom = g;
      if (!geom) {{
        outline.style.display = "none";
        handles.forEach(function(h) {{ h.style.display = "none"; }});
      }} else {{
        positionHandles();
      }}
    }})
    .catch(function(err) {{
      console.error("/geometry fetch failed:", err);
    }});
}}
fetchGeom();
window.addEventListener("design-reload", fetchGeom);
const observer = new ResizeObserver(positionHandles);
observer.observe(canvas);
handles.forEach(function(hEl) {{
  hEl.addEventListener("pointerdown", function(e) {{
    e.preventDefault();
    hEl.setPointerCapture(e.pointerId);
    resizing = {{
      handle: hEl.dataset.handle,
      sg: {{x: geom.x, y: geom.y, w: geom.w, h: geom.h}},
      px: e.clientX,
      py: e.clientY,
    }};
  }});
  hEl.addEventListener("pointermove", function(e) {{
    if (!resizing) return;
    var s  = getScale();
    var dx = Math.round((e.clientX - resizing.px) / s);
    var dy = Math.round((e.clientY - resizing.py) / s);
    var sg = resizing.sg;
    var r;
    var h = resizing.handle;
    if (h === "w" || h === "e") {{
      r = applyEdgeResize(
        h, dx, sg.x, sg.w, DISPLAY_W, MIN_RESIZE_DIM
      );
    }} else {{
      r = applyCornerResize(
        h, dx, dy, sg.x, sg.y, sg.w, sg.h,
        MIN_RESIZE_DIM, DISPLAY_W, DISPLAY_H
      );
    }}
    geom = Object.assign(
      {{x: sg.x, y: sg.y, w: sg.w, h: sg.h}}, r
    );
    positionHandles();
    // contentDocument may reference stale DOM during a
    // design-reload; null-checks prevent errors but the
    // scale may target the outgoing document.
    var doc = svgObj.contentDocument;
    if (doc) {{
      var inner = doc.querySelector("svg > svg");
      if (inner) {{
        inner.setAttribute("x", String(geom.x));
        inner.setAttribute("y", String(geom.y));
        scaleSvgPreview(inner, sg.w, sg.h, geom.w, geom.h);
      }}
    }}
  }});
  hEl.addEventListener("pointerup", function() {{
    if (!resizing) return;
    var committed = {{
      x: geom.x, y: geom.y, w: geom.w, h: geom.h,
    }};
    var doc = svgObj.contentDocument;
    if (doc) {{
      var inner = doc.querySelector("svg > svg");
      if (inner) clearSvgScale(inner);
    }}
    resizing = null;
    fetch("/data")
      .then(function(r) {{
        if (!r.ok) throw new Error("GET /data: " + r.status);
        return r.json();
      }})
      .then(function(data) {{
        var w = data.widget || (data.widgets && data.widgets[0]);
        if (w) {{
          w.x = committed.x;
          w.y = committed.y;
          w.w = committed.w;
          w.h = committed.h;
        }}
        fetch("/data", {{
          method: "POST",
          headers: {{"Content-Type": "application/json"}},
          body: JSON.stringify(data),
        }}).catch(function(err) {{
          console.error("POST /data failed:", err);
        }});
        var ta = document.getElementById("data-editor");
        ta.value = JSON.stringify(data, null, 2);
      }})
      .catch(function(err) {{
        console.error("GET /data failed:", err);
      }});
  }});
  hEl.addEventListener("pointercancel", function() {{
    if (!resizing) return;
    var sg = resizing.sg;
    geom = {{x: sg.x, y: sg.y, w: sg.w, h: sg.h}};
    positionHandles();
    resizing = null;
  }});
}});
</script>
</body>
</html>
"""


# -------------------------------------------------------------------
# Shared state
# -------------------------------------------------------------------


class _DesignState:
    """Shared mutable state for the design tool server.

    Holds the current widget list, display config, device
    preset, and the threading event used to signal file changes
    to SSE clients.

    Attributes:
        widget_type: Display label for the current mode (e.g.
            ``"weather"`` in single-widget mode or
            ``"weather + tile + waste_schedule"`` in multi-widget
            mode).
        widgets: List of widget configuration dicts.  Single-widget
            mode stores one element; multi-widget mode stores many.
        multi: True when showing multiple widgets together; False
            when showing a single widget with resize-handle support.
        states: Entity state dict (separate from config so the
            data editor can reconstruct the JSON).
        config: Display configuration dict.
        preset: Device preset for display info.
        port: Server port number.
        data_path: Path to the custom data file, or None.
        change_event: Threading event set by the file watcher.
        _lock: Protects widgets, states, widget_type, and config
            against concurrent reads and writes.
    """

    def __init__(
        self,
        widget_type: str,
        widgets: list[dict],
        multi: bool,
        states: dict,
        config: dict,
        preset: DevicePreset,
        port: int,
        data_path: Path | None = None,
    ) -> None:
        """Initialize the design state."""
        self.widget_type = widget_type
        self.widgets = widgets
        self.multi = multi
        self.states = states
        self.config = config
        self.preset = preset
        self.port = port
        self.data_path = data_path
        self.change_event = threading.Event()
        self._lock = threading.Lock()

    def apply_data(self, widgets: list[dict], states: dict) -> None:
        """Replace the current widget list and states from the editor.

        Rebuilds the display config from the device preset and
        the new states so the next render uses the updated data.

        Args:
            widgets: New list of widget configuration dicts.
            states: New entity state dict.
        """
        extra: dict = {}
        # Inject battery level when any widget is device_battery.
        if any(w.get("type") == WidgetType.DEVICE_BATTERY for w in widgets):
            extra["device_battery_level"] = 72
        config = _build_config(self.preset, states, **extra)
        label = " + ".join(w.get("type", "?") for w in widgets)
        with self._lock:
            self.widgets = widgets
            self.multi = len(widgets) > 1
            self.states = states
            self.widget_type = label
            self.config = config

    def reload_data(self) -> None:
        """Re-read the data file and update widget/config.

        Called by the file watcher when the ``--data`` file
        changes.  Errors are logged but do not crash the
        server.
        """
        if self.data_path is None:
            return
        try:
            widgets, states = _load_data_file(self.data_path)
            self.apply_data(widgets, states)
            _logger.info("Data file reloaded: %s", self.data_path)
        except Exception:
            _logger.exception("Failed to reload data file")

    def snapshot(self) -> tuple[list[dict], dict, bool]:
        """Return a consistent (widgets, config, multi) triple.

        Returns:
            Tuple of widget list, config dict, and multi flag,
            all captured under the internal lock.
        """
        with self._lock:
            return self.widgets, self.config, self.multi

    def data_json(self) -> str:
        """Serialize the current widget(s) and states as JSON.

        In single-widget mode, uses ``widget`` key for backward
        compatibility with ``--data`` file round-trips.  In
        multi-widget mode, uses ``widgets`` (a list).

        Returns:
            Pretty-printed JSON string.
        """
        with self._lock:
            if self.multi:
                payload: dict = {
                    "widgets": self.widgets,
                    "states": self.states,
                }
            else:
                payload = {
                    "widget": self.widgets[0],
                    "states": self.states,
                }
            return json.dumps(payload, indent=2)


# -------------------------------------------------------------------
# Data file loading
# -------------------------------------------------------------------


def _load_data_file(path: Path) -> tuple[list[dict], dict]:
    """Load widget(s) and states from a JSON or YAML file.

    Accepts two formats::

        {"widget": {"type": "weather", ...}, "states": {...}}
        {"widgets": [{"type": "weather", ...}, ...], "states": {...}}

    Args:
        path: Path to the data file.

    Returns:
        Tuple of ``(widget_list, states_dict)``.

    Raises:
        ValueError: If the file format is unsupported or neither
            ``widget`` nor ``widgets`` key is present.

    Note:
        The ``states`` key is optional and defaults to an empty dict.
    """
    text = path.read_text()
    if path.suffix in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError:
            raise ValueError(
                "PyYAML required for .yaml data files. "
                "Install with: uv pip install pyyaml"
            ) from None
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)

    if not isinstance(data, dict):
        raise ValueError(f"Data file must contain a JSON/YAML object: {path}")
    states = data.get("states", {})
    if "widgets" in data:
        widgets = data["widgets"]
        if (
            not isinstance(widgets, list)
            or not widgets
            or not all(isinstance(w, dict) for w in widgets)
        ):
            raise ValueError(
                f"'widgets' must be a non-empty list of objects: {path}"
            )
        return widgets, states
    widget = data.get("widget")
    if not widget:
        raise ValueError(
            f"Data file must have a 'widget' or 'widgets' key: {path}"
        )
    return [widget], states


# -------------------------------------------------------------------
# File watcher
# -------------------------------------------------------------------

_WATCHED_EXTENSIONS = frozenset((".j2", ".json", ".yaml", ".yml"))


class _ChangeHandler(FileSystemEventHandler):
    """Signal file changes to SSE clients via a threading event.

    Watches for modifications to Jinja2 templates and data
    files.  Applies a 200ms debounce so rapid successive
    edits (e.g. editor auto-save) produce only one reload.
    """

    def __init__(
        self,
        event: threading.Event,
        state: _DesignState,
    ) -> None:
        """Initialize with a change event and design state.

        Args:
            event: Threading event to set on file change.
            state: Shared design state (for data-file reload).
        """
        super().__init__()
        self._event = event
        self._state = state
        self._last_trigger = 0.0

    def on_modified(self, event) -> None:  # type: ignore[override]
        """Handle file modification events.

        Args:
            event: Watchdog file system event.
        """
        if event.is_directory:
            return
        src = event.src_path
        if not any(src.endswith(ext) for ext in _WATCHED_EXTENSIONS):
            return
        now = time.monotonic()
        if now - self._last_trigger < 0.2:
            return
        self._last_trigger = now
        _logger.info("Change detected: %s", src)
        # Reload data file if it was the one that changed.
        data_path = self._state.data_path
        if data_path and Path(src).resolve() == data_path.resolve():
            self._state.reload_data()
        self._event.set()


# -------------------------------------------------------------------
# HTTP handler
# -------------------------------------------------------------------


class _DesignHandler(BaseHTTPRequestHandler):
    """HTTP handler for the design tool preview server.

    Routes:
        ``GET  /``                  -- HTML preview page
        ``GET  /svg``               -- raw SVG (``image/svg+xml``)
        ``GET  /png``               -- resvg-rasterized PNG
        ``GET  /optimized.png``     -- e-ink optimized PNG
        ``GET  /data``              -- widget + states JSON
        ``GET  /geometry``          -- effective widget bounds
        ``GET  /js/resize-math.js`` -- compiled resize math
        ``GET  /events``            -- SSE endpoint for reload
        ``POST /data``              -- update widget + states
    """

    server: _DesignServer

    def do_GET(self) -> None:
        """Route GET requests to the matching endpoint."""
        path = self.path.split("?")[0]
        routes = {
            "/": self._serve_html,
            "/favicon.png": self._serve_favicon,
            "/svg": self._serve_svg,
            "/png": self._serve_png,
            "/optimized.png": self._serve_optimized,
            "/data": self._serve_data,
            "/geometry": self._serve_geometry,
            "/js/resize-math.js": self._serve_resize_math,
            "/events": self._serve_sse,
        }
        handler = routes.get(path)
        if handler:
            handler()
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        """Route POST requests to the matching endpoint."""
        path = self.path.split("?")[0]
        routes = {
            "/data": self._handle_data_post,
        }
        handler = routes.get(path)
        if handler:
            handler()
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def _state(self) -> _DesignState:
        """Access the shared design state from the server.

        Returns:
            The ``_DesignState`` instance attached to the
            server.
        """
        return self.server.design_state

    def _serve_html(self) -> None:
        """Serve the three-panel HTML preview page."""
        st = self._state()
        initial = html.escape(st.data_json())
        page = _HTML_TEMPLATE.format(
            widget_type=st.widget_type,
            device_name=st.preset.label,
            width=st.preset.width,
            height=st.preset.height,
            grayscale_levels=st.preset.grayscale_levels,
            port=st.port,
            initial_data=initial,
        )
        body = page.encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_data(self) -> None:
        """Serve the current widget and states as JSON."""
        body = self._state().data_json().encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _serve_geometry(self) -> None:
        """Serve the effective widget bounds as JSON.

        In single-widget mode, renders the widget SVG and reads
        ``width``/``height`` from the root ``<svg>`` tag so the
        browser can position resize handles around the rendered
        content.

        In multi-widget mode, returns ``null`` so the browser hides
        the resize handles (they only make sense for a single
        widget).
        """
        widgets, config, multi = self._state().snapshot()
        if multi:
            body = b"null"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)
            return
        widget = widgets[0]
        x = widget.get("x", PADDING)
        y = widget.get("y", 0)
        # Render the widget to read actual content dimensions from
        # the SVG root tag rather than falling back to the full
        # display size.
        svg = render_widget_svg(widget, config)
        m = re.search(r'width="(\d+)"', svg)
        w = int(m.group(1)) if m else config["width"] - x
        m = re.search(r'height="(\d+)"', svg)
        h = int(m.group(1)) if m else config["height"] - y
        body = json.dumps({"x": x, "y": y, "w": w, "h": h}).encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _serve_favicon(self) -> None:
        """Serve the brand icon as a PNG favicon."""
        body = _BRAND_ICON.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_resize_math(self) -> None:
        """Serve the compiled resize-math.js ESM module.

        Reads the file built by ``pnpm build`` from the frontend
        directory.  Returns 503 with a human-readable error when the
        file has not been built yet.
        """
        if not _RESIZE_MATH_JS.exists():
            self._text_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "resize-math.js not built. Run:\n"
                "  pnpm --dir custom_components/"
                "eink_dashboard/frontend build",
            )
            return
        body = _RESIZE_MATH_JS.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/javascript")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _handle_data_post(self) -> None:
        """Accept new widget(s) + states JSON from the editor.

        Validates the JSON payload, updates the shared state,
        and triggers an SSE reload so all panels re-render.
        Accepts both ``{"widget": {...}}`` (single, backward-
        compatible) and ``{"widgets": [...]}`` (multi-widget).
        The ``states`` key is optional and defaults to an empty dict.
        """
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            self._text_response(
                HTTPStatus.BAD_REQUEST,
                f"Invalid JSON: {exc}",
            )
            return
        states = data.get("states", {})
        if "widgets" in data:
            widgets = data["widgets"]
            if (
                not isinstance(widgets, list)
                or not widgets
                or not all(isinstance(w, dict) for w in widgets)
            ):
                self._text_response(
                    HTTPStatus.BAD_REQUEST,
                    "'widgets' must be a non-empty list of objects.",
                )
                return
        elif "widget" in data:
            widget = data["widget"]
            if not isinstance(widget, dict) or not widget:
                self._text_response(
                    HTTPStatus.BAD_REQUEST,
                    "Missing or empty 'widget' key.",
                )
                return
            widgets = [widget]
        else:
            self._text_response(
                HTTPStatus.BAD_REQUEST,
                "Payload must have a 'widget' or 'widgets' key.",
            )
            return
        st = self._state()
        st.apply_data(widgets, states)
        st.change_event.set()
        self._text_response(HTTPStatus.OK, "OK")

    def _text_response(self, status: HTTPStatus, text: str) -> None:
        """Send a plain-text HTTP response.

        Args:
            status: HTTP status code.
            text: Response body.
        """
        body = text.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_svg(self) -> None:
        """Serve the raw SVG for the current widget(s)."""
        try:
            widgets, config, _ = self._state().snapshot()
            svg = _render_svg(widgets, config)
            body = svg.encode()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "image/svg+xml")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)
        except Exception:
            self._serve_error_svg(traceback.format_exc())

    def _serve_png(self) -> None:
        """Serve the resvg-rasterized PNG."""
        try:
            widgets, config, _ = self._state().snapshot()
            svg = _render_svg(widgets, config)
            png = _render_png(svg, config)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(png)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(png)
        except Exception:
            self._serve_error_svg(traceback.format_exc())

    def _serve_optimized(self) -> None:
        """Serve the e-ink optimized PNG."""
        try:
            widgets, config, _ = self._state().snapshot()
            svg = _render_svg(widgets, config)
            png = _render_png(svg, config)
            opt = _render_optimized(png, config)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(opt)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(opt)
        except Exception:
            self._serve_error_svg(traceback.format_exc())

    def _serve_error_svg(self, message: str) -> None:
        """Return a rendering error as an SVG image.

        Args:
            message: Error traceback text to display.
        """
        safe = (
            message.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        lines = safe.split("\n")[:20]
        text_els = "".join(
            f'<text x="10" y="{30 + i * 16}" '
            f'font-size="12" fill="red" '
            f'font-family="monospace">{ln}</text>'
            for i, ln in enumerate(lines)
        )
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg"'
            ' width="600" height="400">'
            '<rect width="600" height="400" fill="white"/>'
            f"{text_els}</svg>"
        )
        body = svg.encode()
        # 200 is intentional: <img> tags hide content on
        # error status codes, making the error invisible.
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/svg+xml")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_sse(self) -> None:
        """Serve the SSE endpoint for live reload.

        Keeps the connection open and sends ``reload`` events
        when the file watcher detects template changes.  Sends
        a keepalive comment every 15 seconds to prevent proxy
        timeouts.
        """
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        # Single Event means only one SSE client reliably
        # receives each notification (acceptable for a
        # single-tab dev tool).
        change_event = self._state().change_event
        try:
            # Flush an initial comment so Firefox's EventSource sees a
            # live connection immediately rather than timing out before
            # the first keepalive tick (15 s).
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                triggered = change_event.wait(timeout=15.0)
                if triggered:
                    change_event.clear()
                    self.wfile.write(b"data: reload\n\n")
                    self.wfile.flush()
                else:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, format: str, *args: object) -> None:
        """Route access logs through the module logger.

        Suppresses noisy SSE keepalive polling.

        Args:
            format: Log format string.
            *args: Format arguments.
        """
        if args and "/events" in str(args[0]):
            return
        _logger.debug(format, *args)


class _DesignServer(ThreadingHTTPServer):
    """Threaded HTTP server with attached design state.

    Attributes:
        design_state: Shared ``_DesignState`` instance
            accessible by all request handler threads.
    """

    design_state: _DesignState


# -------------------------------------------------------------------
# CLI
# -------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed namespace with ``device``, ``widget``, ``port``,
        and ``data`` attributes.
    """
    parser = argparse.ArgumentParser(
        description=("Live-preview e-ink widget templates in a browser."),
    )
    known = sorted(_MOCK_DATA.keys())
    parser.add_argument(
        "--widget",
        default=None,
        metavar="TYPE",
        help=(
            "Widget type to preview in single-widget mode. "
            "Known types with built-in mock data: "
            + ", ".join(known)
            + ". Any other value starts with an empty skeleton. "
            "Omit to show a multi-widget dashboard preview "
            "(weather + tile + waste_schedule)."
        ),
    )
    parser.add_argument(
        "--device",
        choices=sorted(k for k in DEVICE_PRESETS if k != "custom"),
        default="kindle_pw",
        help="Device preset (default: kindle_pw).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8088,
        help="HTTP server port (default: 8088).",
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=None,
        metavar="FILE",
        help=(
            "JSON/YAML file with widget config and entity "
            "states.  Overrides --widget mock data."
        ),
    )
    return parser.parse_args()


# -------------------------------------------------------------------
# Entry point
# -------------------------------------------------------------------


def _ensure_resize_math() -> None:
    """Build resize-math.js if missing or older than its TypeScript source.

    Runs ``pnpm build`` in the frontend directory so the design tool
    works out of the box without a separate manual build step.
    """
    needs_build = not _RESIZE_MATH_JS.exists() or (
        _RESIZE_MATH_TS.stat().st_mtime > _RESIZE_MATH_JS.stat().st_mtime
    )
    if not needs_build:
        return
    _logger.info("Building resize-math.js …")
    subprocess.run(
        ["pnpm", "build"],
        cwd=_FRONTEND_DIR,
        check=True,
    )


# Default dashboard layout for multi-widget mode.
# Each entry is (widget_type, overrides) where overrides are merged
# into the mock widget dict.  Layout (1024 px tall):
#   weather ~300 px | tile 56 | entity 112 | sensor 112 |
#   waste_schedule 168 | device_battery 40 (bottom-right corner)
_DEFAULT_DASHBOARD: list[tuple[str, dict]] = [
    (WidgetType.WEATHER, {"y": 10}),
    (WidgetType.TILE, {"y": 320}),
    (WidgetType.ENTITY, {"y": 386}),
    (WidgetType.SENSOR, {"y": 508}),
    (WidgetType.WASTE_SCHEDULE, {"y": 630}),
    # Bottom-right corner: x=634 leaves 124 px to the right edge.
    (WidgetType.DEVICE_BATTERY, {"y": 960, "x": 634}),
]


def main() -> None:
    """Start the design tool server."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    _ensure_resize_math()
    args = _parse_args()
    preset = DEVICE_PRESETS[args.device]

    multi: bool
    widgets: list[dict]
    states: dict

    if args.data:
        try:
            widgets, states = _load_data_file(args.data)
        except ValueError as exc:
            sys.exit(str(exc))
        widget_type = " + ".join(w.get("type", "?") for w in widgets)
        multi = len(widgets) > 1
    elif args.widget is None:
        # Default: compose a multi-widget dashboard preview.
        widgets = []
        states = {}
        for wtype, overrides in _DEFAULT_DASHBOARD:
            base, ws = _MOCK_DATA[wtype]
            widgets.append({**base, **overrides})
            states.update(ws)
        widget_type = "dashboard"
        multi = True
    elif args.widget in _MOCK_DATA:
        widget_type = args.widget
        base_widget, states = _MOCK_DATA[args.widget]
        widgets = [{**base_widget}]
        multi = False
    else:
        widget_type = args.widget
        widgets = [{"type": widget_type, "x": 24, "y": 10}]
        states = {}
        multi = False
        _logger.info(
            "No mock data for '%s' — starting with empty skeleton",
            widget_type,
        )

    extra: dict = {}
    if any(w.get("type") == WidgetType.DEVICE_BATTERY for w in widgets):
        extra["device_battery_level"] = 72

    config = _build_config(preset, states, **extra)

    state = _DesignState(
        widget_type=widget_type,
        widgets=widgets,
        multi=multi,
        states=states,
        config=config,
        preset=preset,
        port=args.port,
        data_path=args.data,
    )

    # File watcher: monitor templates/ for .j2 changes.
    observer = Observer()
    handler = _ChangeHandler(state.change_event, state)
    observer.schedule(handler, str(_TEMPLATE_DIR), recursive=True)
    if args.data:
        observer.schedule(
            handler,
            str(args.data.parent.resolve()),
            recursive=False,
        )
    observer.start()

    # HTTP server.
    server = _DesignServer(("127.0.0.1", args.port), _DesignHandler)
    server.design_state = state

    url = f"http://localhost:{args.port}"
    _logger.info("Design tool running at %s", url)
    _logger.info(
        "Mode: %s | Device: %s (%dx%d, %d-level)",
        widget_type,
        preset.label,
        preset.width,
        preset.height,
        preset.grayscale_levels,
    )
    _logger.info("Press Ctrl+C to stop.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _logger.info("Shutting down.")
    finally:
        observer.stop()
        observer.join()
        server.server_close()


if __name__ == "__main__":
    main()
