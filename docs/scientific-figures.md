# Read the forecast maps

The map shows a **condition index from 0 to 1**. Larger values mean that the
implemented conditions and modifiers combine to give a larger score. The index
is an uncalibrated heuristic, not a probability, observed sky color, or measured
forecast skill. A value of 0.8 does not mean an 80% chance of a colorful sky.

## Read a local map

1. Check the location, event day, and local event time in the header.
2. Read the nearest evaluation cell's score as `Center index` in the header.
3. Compare nearby cells with the horizontal index scale. Gray means no data.
4. Check the weather model's initialization and valid time in the footer.
5. Open the JSON sidecar for source details, input limits, and diagnostics.

The crosshair marks the requested coordinates. Its score comes from the nearest
computed cell, rather than an interpolated value. A zero score is valid data and
uses the lowest index color. It can occur when a necessary condition fails.
Gray cells have missing values; they do not imply a low score. Context outside
the evaluated field is background map area, not missing forecast data.

## What the colors preserve

New maps draw each computed grid cell directly. They do not smooth, upsample, or
interpolate the index field. Cell edges are derived from neighboring coordinate
centers. Missing values remain masked. An isolated high value stays high; a zero
surrounded by larger values stays zero. This avoids visual changes to peaks,
gates, and missing-data coverage.

The sequential blue scale uses the existing class boundaries:
`0, 0.20, 0.40, 0.50, 0.70, 0.85, 1.00`. These are display bins, not calibrated
forecast categories. The legacy 0.50 reference remains in compatible metadata;
it is not an established threshold for a visible event. A small difference across
a bin boundary can change the color, so use numeric values for precise comparisons.
Index colors do not represent predicted sky colors.

The [color guide](../examples/color-guide/README.md) shows every interval with
exact example values and four constructed fields. These are synthetic illustrations,
not weather forecasts. Pale and dark areas show smaller and larger scores;
they do not identify physical cloud layers. Gray is outside the numeric scale.

| Example value | Display interval |
| ---: | --- |
| 0.10 | `0.00 ≤ index < 0.20` |
| 0.30 | `0.20 ≤ index < 0.40` |
| 0.45 | `0.40 ≤ index < 0.50` |
| 0.60 | `0.50 ≤ index < 0.70` |
| 0.78 | `0.70 ≤ index < 0.85` |
| 0.93 | `0.85 ≤ index ≤ 1.00` |

An exact boundary enters the darker interval. Two different values can share a
color: 0.51 and 0.69 are both in the fourth interval. Numbers are needed for exact
comparison. The selected location's score is separate from nearby cells; a dark
patch nearby does not assign its score to the observer crosshair.

The map is the main panel. A compact scale and source footer replace the former
threshold headline, repeated city table, and multiple contour-label families.
National city sample values remain available in metadata.

## Geometry and resolution

Local maps use an approximate equirectangular display. The longitude-to-latitude
aspect is corrected at the field's central latitude. This is suitable for local
orientation but is not a surveyed distance map. China national maps use a Lambert
conformal conic projection with explicit longitude/latitude transforms. The
colored national field and missing-data fill are clipped to the country boundary.
Map boundaries provide context; they do not alter the computed score.

The footer separates evaluation-grid spacing from source-model resolution.
For example, sampling local scores at 0.1° does not increase GFS's 0.25° weather
resolution. Neighboring scores can reuse the same coarse weather information.
The requested radius creates the local evaluation bounds; the plotted grid is
rectangular and does not imply an exact circular coverage area.

## Event time and weather time

The exact solar event and the weather forecast's discrete valid time are different
quantities. A request at 17:00 for a 19:00 sunset uses available forecast data for
the event, not simply the atmosphere forecast for 17:00. Model-hour selection can
put the weather valid time before or after the exact event. The footer and JSON
keep those times separate. For national maps, event times vary across the domain;
the valid-time range is not one sunset instant for every cell.

GFS initialization identifies the model run. GFS valid time identifies the
forecasted atmosphere used by the product. The generated time is the recorded
product timestamp; it can be the request/as-of time passed into generation.
It does not establish when rendering or delivery completed. Attempt records keep
actual completion time separately. Open-Meteo source times, when available, are recorded
separately in JSON. A readable figure does not resolve cloud-boundary, aerosol,
terrain, or timing uncertainty at model resolution.

## Reproducibility and older products

PNG files and their JSON sidecars belong together. Display metadata records the
rendering method, palette, class bounds, grid handling, and projection. Numerical
scores and weather-source provenance are preserved separately from presentation.
The redesign does not change the forecast algorithm.

Archived example images and original forecast attempts keep their original
appearance and checksums. A remotely downloaded product can also use an older
renderer. Check its sidecar before assuming that it uses the new raw-cell display.
Do not rewrite an archived forecast to make it appear newly issued.

The rendering choices follow Matplotlib's guidance on
[sequential color scales](https://matplotlib.org/stable/users/explain/colors/colormaps.html)
and [mesh cell coordinates](https://matplotlib.org/stable/api/_as_gen/matplotlib.axes.Axes.pcolormesh.html),
and Cartopy's distinction between
[projection and coordinate transforms](https://cartopy.readthedocs.io/stable/tutorials/understanding_transform.html).
