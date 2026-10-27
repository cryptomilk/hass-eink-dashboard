# Copyright 2026 Andreas Schneider
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Static types for the widget configs stored as JSON.

Widgets are persisted and received from the frontend as plain dicts, so
these ``TypedDict`` classes exist only for ``ty``: they add no runtime
validation, and unknown keys sent by a newer frontend stay harmless.
Stored JSON may omit any key, so every class declares ``total=False``
itself; the flag is not inherited by subclasses.  Numeric keys are
typed ``int | float | str`` where the editor may store numbers as
strings, so readers convert them at the read site.

Each widget type has one ``<Name>Widget`` class mirroring the
interfaces in ``frontend/src/types/ha.d.ts``.  Helpers shared by
several widget types take the narrow mixin class holding the keys they
read:

- ``WidgetBase``: ``resolve_font()``, ``_widget_dim()``
- ``EntityFields``: ``_resolve_entity()``
- ``DecimalsFields``: ``_resolve_precision()``
- ``IconFields``: ``_resolve_entity_icon()``
- ``InvertFields``: ``_resolve_invert()``
- ``ListFields``: ``_max_row_height()``, ``_divider_stroke_width()``
- ``EntityInfoWidget``: ``_entity_info_context()``
"""

from typing import TypedDict


class FontSpec(TypedDict, total=False):
    """Override of one text role's font."""

    size: int | float | str
    """Absolute pixel size; omitted keeps the scaled default."""
    weight: str
    """``"regular"``, ``"medium"`` or ``"bold"``."""


class Condition(TypedDict, total=False):
    """A Lovelace visibility condition, possibly nested."""

    condition: str
    """Condition kind; absent means a legacy state check."""
    entity: str
    """Entity ID whose state is tested."""
    state: str | list[str]
    """State(s) that satisfy the condition."""
    state_not: str | list[str]
    """State(s) that fail the condition."""
    above: str | int | float
    """Numeric lower bound (exclusive)."""
    below: str | int | float
    """Numeric upper bound (exclusive)."""
    after: str
    """Time of day after which a ``time`` condition holds."""
    before: str
    """Time of day before which a ``time`` condition holds."""
    weekdays: list[str]
    """Weekdays on which a ``time`` condition holds."""
    conditions: list["Condition"]
    """Children of an ``and`` / ``or`` / ``not`` condition."""


class WidgetBase(TypedDict, total=False):
    """Keys shared by every widget type."""

    type: str
    """``WidgetType`` value selecting the renderer."""
    label: str
    """Editor-only display label."""
    description: str
    """Editor-only note."""
    x: int
    """Left edge in pixels."""
    y: int
    """Top edge in pixels."""
    w: int
    """Width in pixels."""
    h: int
    """Height in pixels."""
    fonts: dict[str, FontSpec]
    """Per-role font overrides; roles are widget-specific."""
    card_style: str
    """``"border"``, ``"left_bar"`` or ``"none"``."""
    visibility: list[Condition]
    """Conditions that must all hold for the widget to render."""


class DecimalsFields(TypedDict, total=False):
    """Key of widgets whose value honours a decimals override."""

    decimals: int
    """Exact decimal places; overrides HA's display precision."""


class EntityFields(DecimalsFields, total=False):
    """Keys of widgets that display one entity."""

    entity: str
    """Entity ID."""
    name: str
    """Display name override."""
    unit: str
    """Unit override."""
    hide_name: bool
    """Suppress the name."""
    attribute: str
    """Attribute to show instead of the state."""


class ListFields(TypedDict, total=False):
    """Keys of widgets that stack titled rows."""

    title: str
    """Title drawn above the rows."""
    row_height: int
    """Maximum row height in pixels."""
    divider_width: int
    """Divider stroke width in pixels."""


class IconFields(TypedDict, total=False):
    """Keys of widgets that draw an entity icon."""

    icon: str
    """MDI icon override, e.g. ``"mdi:lightbulb"``."""
    icon_style: str
    """``"filled"``, ``"outlined"`` or ``"none"``."""
    hide_icon: bool
    """Suppress the icon."""


class InvertFields(TypedDict, total=False):
    """Keys of widgets that can render inverted."""

    invert_condition: list[Condition]
    """Conditions that, when all met, invert the widget."""


class EntityInfoWidget(WidgetBase, EntityFields, IconFields, total=False):
    """Keys read by the shared entity header (icon, name, value)."""


class SeparatorWidget(WidgetBase, total=False):
    """Separator widget config."""

    direction: str
    """``"horizontal"`` or ``"vertical"``."""
    style: str
    """``"line"`` or ``"bar"``."""
    length: int | None
    """Line length in pixels; ``None`` spans the widget."""


class FrameWidget(WidgetBase, total=False):
    """Frame widget config."""

    border_width: int
    """Border stroke width in pixels."""
    border_radius: int
    """Corner radius in pixels."""
    color: int
    """Border gray level, 0-255."""
    fill_color: int | None
    """Fill gray level, 0-255; ``None`` leaves the frame unfilled."""


class EntitiesRow(TypedDict, total=False):
    """One row of the entities widget."""

    type: str
    """``"divider"`` or ``"section"``; absent for an entity row."""
    label: str
    """Section heading text."""
    entity: str
    """Entity ID of an entity row."""
    name: str
    """Display name override."""
    icon: str
    """MDI icon override."""


class EntitiesWidget(WidgetBase, ListFields, DecimalsFields, total=False):
    """Entities (list) widget config."""

    entities: list[str | EntitiesRow]
    """Entity IDs or row dicts, in display order."""
    icon_style: str
    """``"filled"``, ``"outlined"`` or ``"none"``."""
    hide_icon: bool
    """Suppress the row icons."""


class EntityWidget(
    WidgetBase, EntityFields, IconFields, InvertFields, total=False
):
    """Entity widget config."""

    name_position: str
    """``"top"`` or ``"bottom"``."""
    name_align: str
    """``"left"`` or ``"right"``."""


GaugeSegment = TypedDict(
    "GaugeSegment",
    {
        "from": int | float | str,
        "color": int | str | list[int],
        "label": str,
        "icon": str | None,
    },
    total=False,
)
"""One colored gauge segment.

``from`` is the value where the segment starts.  ``color`` is a gray
level, a ``"#rrggbb"`` string or an ``[r, g, b]`` list.  The functional
syntax is needed because ``from`` is a Python keyword.
"""


class GaugeWidget(WidgetBase, EntityFields, total=False):
    """Gauge widget config."""

    icon: str
    """MDI icon override.

    Declared here rather than via ``IconFields``: the gauge reads
    neither ``icon_style`` nor ``hide_icon``.
    """
    gauge_type: str
    """``"standard"``, ``"half"`` or ``"full"``."""
    header_position: str
    """``"bottom"`` or ``"top"``."""
    needle: bool
    """Draw a needle instead of a filled arc."""
    min: int | float | str
    """Value at the start of the scale."""
    max: int | float | str
    """Value at the end of the scale."""
    segments: list[GaugeSegment]
    """Colored ranges along the scale."""
    show_unit: bool
    """Append the unit to the value."""


class GraphEntityConfig(TypedDict, total=False):
    """One series of the graph widget."""

    entity: str
    """Entity ID."""
    name: str
    """Legend name override."""
    y_axis: str
    """``"primary"`` or ``"secondary"``."""
    line_style: str
    """``"solid"``, ``"dashed"`` or ``"dotted"``."""
    data_source: str
    """``"history"`` or ``"attribute"``."""
    attribute: str
    """Attribute holding the series when ``data_source`` is
    ``"attribute"``."""
    attribute_timestamp_key: str
    """Key of the timestamp inside each attribute item."""
    attribute_value_key: str
    """Key of the value inside each attribute item."""


class GraphColorThreshold(TypedDict, total=False):
    """A color change at a value of the graph widget."""

    value: int | float | str
    """Value at which the color starts."""
    color: str
    """``"#rrggbb"`` color."""
    shade: str
    """``"black"``, ``"dark"``, ``"medium"`` or ``"light"`` for
    2-level displays."""


class GraphWidget(EntityInfoWidget, total=False):
    """Graph widget config.

    ``entity``, ``name`` and ``decimals`` configure the single-series
    form; ``entities`` configures several series.  The numbered keys
    are the flat editor form of the second and third series and of the
    color thresholds.
    """

    entities: list[str | GraphEntityConfig]
    """Series; replaces ``entity`` when set."""
    data_source: str
    """``"history"`` or ``"attribute"`` for the single series."""
    attribute_timestamp_key: str
    """Timestamp key of the single attribute series."""
    attribute_value_key: str
    """Value key of the single attribute series."""
    entity_2: str
    """Second series entity ID."""
    entity_3: str
    """Third series entity ID."""
    name_2: str
    """Second series legend name."""
    name_3: str
    """Third series legend name."""
    y_axis_2: str
    """Second series axis, ``"primary"`` or ``"secondary"``."""
    y_axis_3: str
    """Third series axis, ``"primary"`` or ``"secondary"``."""
    hours_to_show: int | float | str
    """History window in hours."""
    start_time: str
    """Anchor of the history window."""
    points_per_hour: int | float | str
    """Sampling density of the series."""
    aggregate_func: str
    """Aggregation applied per sample bucket."""
    group_by: str
    """Bucketing mode."""
    line_width: int | float | str
    """Series stroke width in pixels."""
    upper_bound: int | float | str | None
    """Fixed upper end of the primary axis."""
    lower_bound: int | float | str | None
    """Fixed lower end of the primary axis."""
    min_bound_range: int | float | str | None
    """Minimum span of the primary axis."""
    secondary_upper_bound: int | float | str | None
    """Fixed upper end of the secondary axis."""
    secondary_lower_bound: int | float | str | None
    """Fixed lower end of the secondary axis."""
    smoothing: bool
    """Smooth the line."""
    show_fill: bool
    """Fill below the line."""
    show_labels: bool
    """Draw axis labels."""
    show_extrema: bool
    """Mark the minimum and maximum."""
    show_state: bool
    """Show the current state in the header."""
    show_name: bool
    """Show the name in the header."""
    show_icon: bool
    """Show the icon in the header."""
    show_legend: bool
    """Show the series legend."""
    graph: str
    """``"line"`` or ``"bar"``."""
    color_thresholds: list[GraphColorThreshold]
    """Color changes along the value axis."""
    color_thresholds_transition: str
    """``"smooth"`` or ``"hard"``."""
    threshold_1_value: int | float | str
    """Flat editor form of the first threshold value."""
    threshold_1_color: str
    """Flat editor form of the first threshold color."""
    threshold_1_shade: str
    """Flat editor form of the first threshold shade."""
    threshold_2_value: int | float | str
    """Flat editor form of the second threshold value."""
    threshold_2_color: str
    """Flat editor form of the second threshold color."""
    threshold_2_shade: str
    """Flat editor form of the second threshold shade."""
    threshold_3_value: int | float | str
    """Flat editor form of the third threshold value."""
    threshold_3_color: str
    """Flat editor form of the third threshold color."""
    threshold_3_shade: str
    """Flat editor form of the third threshold shade."""
    threshold_4_value: int | float | str
    """Flat editor form of the fourth threshold value."""
    threshold_4_color: str
    """Flat editor form of the fourth threshold color."""
    threshold_4_shade: str
    """Flat editor form of the fourth threshold shade."""
    x_axis_ticks: int | str
    """Number of x axis labels."""
    y_axis_ticks: int | str
    """Number of y axis labels."""
    x_axis_tick_marks: bool
    """Draw x axis tick marks."""
    y_axis_tick_marks: bool
    """Draw y axis tick marks."""
    x_axis_grid: bool
    """Draw vertical grid lines."""
    y_axis_grid: bool
    """Draw horizontal grid lines."""
    y_axis_unit: bool
    """Append the unit to y axis labels."""
    state_font_size: int
    """Header state font size in pixels."""


class HeadingBadge(TypedDict, total=False):
    """A badge shown on the heading widget."""

    entity: str
    """Entity ID."""
    show_icon: bool
    """Show the entity icon."""
    show_state: bool
    """Show the entity state."""
    icon: str
    """MDI icon override; only an ``mdi:`` prefix is honoured."""


class HeadingWidget(WidgetBase, total=False):
    """Heading widget config."""

    heading: str
    """Heading text; rendered from a template before drawing."""
    heading_style: str
    """``"title"`` or ``"subtitle"``."""
    heading_align: str
    """``"left"`` or ``"right"``."""
    icon: str
    """MDI icon.

    Declared here rather than via ``IconFields``: this is the heading's
    own icon, not an entity icon override, and there is no
    ``hide_icon``.
    """
    icon_style: str
    """``"filled"``, ``"outlined"`` or ``"none"``."""
    badges: list[str | HeadingBadge]
    """Entity IDs or badge dicts."""


class SensorLimits(TypedDict, total=False):
    """Sensor graph value range."""

    min: int | float
    """Lower end of the range."""
    max: int | float
    """Upper end of the range."""


class SensorWidget(EntityInfoWidget, total=False):
    """Sensor widget config."""

    graph: str | None
    """``"line"`` to draw a graph; empty or ``None`` for none."""
    detail: int | str
    """Graph detail level."""
    hours_to_show: int | float | str
    """History window in hours."""
    limits: SensorLimits
    """Graph value range."""
    limits_min: int | float | None
    """Flat editor form of ``limits.min``."""
    limits_max: int | float | None
    """Flat editor form of ``limits.max``."""
    hide_fill: bool
    """Do not fill below the graph line."""
    hide_state: bool
    """Suppress the state text."""


class TileWidget(
    WidgetBase, EntityFields, IconFields, InvertFields, total=False
):
    """Tile widget config."""

    hide_state: bool
    """Suppress the secondary state text."""
    state_content: str | list[str]
    """Attribute name or list; the first element is used."""


class WeatherWidget(WidgetBase, total=False):
    """Weather widget config."""

    entity: str
    """Weather entity ID."""
    font_size: int
    """Base font size in pixels."""
    forecast_days: int
    """Number of forecast days to draw."""
    mode: str
    """``"full"``, ``"forecast"`` or ``"current"``."""
    temperature_entity: str
    """Sensor overriding the current temperature."""
    humidity_entity: str
    """Sensor overriding the current humidity."""


class DeviceBatteryWidget(WidgetBase, total=False):
    """Device battery widget config."""

    layout: str
    """``"icon"`` or ``"chip"``."""
    color: int
    """Gray level of the battery, 0-255."""


class WasteScheduleEntry(TypedDict, total=False):
    """One waste collection attribute of the waste schedule widget."""

    attribute: str
    """Entity attribute holding the next collection date."""
    label: str
    """Row label."""


class WasteScheduleWidget(WidgetBase, ListFields, total=False):
    """Waste schedule widget config."""

    entity: str
    """Entity ID carrying the collection attributes."""
    entries: list[WasteScheduleEntry]
    """Rows to show."""
    layout: str
    """``"list"`` or ``"card"``."""
    show_all: bool
    """Show every collection, not only the next one."""
    hide_icon: bool
    """Suppress the row icons."""


class CalendarWidget(WidgetBase, ListFields, total=False):
    """Calendar widget config."""

    entity: str
    """Calendar entity ID."""
    max_events: int
    """Maximum number of events to list."""
    days_ahead: int
    """Days of events to fetch."""
    hide_icon: bool
    """Suppress the row icons."""


class MeteogramWidget(WidgetBase, total=False):
    """Meteogram widget config."""

    entity: str
    """Weather entity ID."""
    show_cloud_cover: bool
    """Draw the cloud cover band."""
    show_precipitation: bool
    """Draw precipitation bars."""
    smoothing: bool
    """Smooth the temperature curve."""
    show_fill: bool
    """Fill below the temperature curve."""
    hours: int | str
    """Forecast window in hours."""
    line_width: int | str
    """Temperature curve width in pixels."""
    day_label_format: str
    """``DayLabelFormat`` value for the day labels."""
