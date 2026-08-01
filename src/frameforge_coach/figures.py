"""Proportion-aware figure structuring — the human-specific coach layer.

Where :mod:`frameforge_coach.clean` lifts *any* traced lines (image-agnostic),
this module is the part that understands a **figure**. It turns an ingested
human silhouette into an analyzed model — anatomical landmarks plus a
proportion signature — and on top of that can:

* **retarget** the figure's proportions onto a named drawing canon
  (piecewise-affine, total height preserved),
* **mirror** a half-figure into a bilaterally symmetric whole,
* run an **advisory plausibility gate** against documented canon ranges.

This is the layer that earns vela-nova's human-specific machinery a place in
the coach: the generic region trace collapses a complex shaded figure into a
black block (demonstrated on the Iron Man ingest), whereas a *width-profile*
read of the silhouette recovers shoulders / waist / hips / knees as structure.

Geometry ported from the sibling repo ``vela-nova-rocket``
(``canonical/lib/{profile,proportion,extract_contour}.py``): 1-D persistence
landmark detection (``_persistence_1d`` / ``find_anatomical_landmarks``), the
``ProportionSignature`` algebra and ``interpolate`` / ``transform_contour``,
and the mirror rebuild in ``_body_mask_from_contour``. Reimplemented in **pure
Python** (no numpy / scipy / cv2) so the package stays import-light, matching
``coach.clean``; the scipy smoothing / extrema are reimplemented with stdlib.

Canon definitions are the classical figure-drawing canons:

* Polykleitos, *Kanon* (c. 450-440 BCE), ~7.5 heads — proportions transmitted
  via Galen, *De placitis Hippocratis et Platonis* V.3.
* Vitruvius, *De Architectura* III.1 (c. 30-15 BCE) — the well-formed body is
  eight heads tall.
* Andrew Loomis, *Figure Drawing for All It's Worth* (Viking, 1943) — the
  "ideal" eight-head and "heroic" ~8.5-head figures, and the elongated fashion
  figure (~8.5-9 heads).

The numeric ratios are adapted from vela-nova's ``CANON_DEFS``, which encode
these sources. Unverified beyond those references — treat as the documented
art canons they are, not as anthropometric measurement.

⚠ ARCHITECTURAL CONTRACT (PALS's LAW) — the plausibility gate is ADVISORY.
It flags signatures that fall outside documented canon ranges; it is NOT a
proof that a shape is, or is not, a valid human figure. A passing report is a
sanity check, never a fidelity guarantee. Treat every result as untrusted.

Boundary: imports only stdlib (per the package-boundary gate). The figure it
analyzes comes from :func:`frameforge_coach.ingest.ingest` upstream.
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from typing import Any, Sequence, Union

Obj = dict[str, Any]
Point = list  # [x, y]
_PT_TYPES = {"polyline", "polygon"}

# Canonical 7-point landmark scheme, crown → toe.
_LANDMARK_NAMES = [
    "head_peak", "neck_valley", "shoulder_peak", "waist_valley",
    "hip_peak", "knee_valley", "ankle_valley",
]

# Detection bands in head-units (crown = 0): (name, dy_lo, dy_hi, kind).
# Ported from vela-nova ``profile._BANDS_7``.
_BANDS_7 = [
    ("head_peak", 0.0, 1.0, "peak"),
    ("neck_valley", 0.7, 1.5, "valley"),
    ("shoulder_peak", 1.2, 2.3, "peak"),
    ("waist_valley", 2.5, 3.5, "valley"),
    ("hip_peak", 3.2, 4.5, "peak"),
    ("knee_valley", 5.2, 6.5, "valley"),
    ("ankle_valley", 7.0, 8.0, "valley"),
]
_MIN_LANDMARK_SEP = 0.25  # min head-units between adjacent landmarks


# ═══════════════════════════════════════════════════════════════
#  Proportion signature
# ═══════════════════════════════════════════════════════════════
@dataclass
class ProportionSignature:
    """A figure's address in proportion space.

    ``segment_ratios`` are the normalized vertical gaps between consecutive
    landmarks (sum ≈ 1). ``width_ratios`` are each landmark's half-width over
    the total landmark-span height. Names/labels carry the anatomy.
    """

    segment_ratios: list
    width_ratios: list
    segment_labels: list
    landmark_names: list

    def __post_init__(self) -> None:
        self.segment_ratios = [float(r) for r in self.segment_ratios]
        self.width_ratios = [float(w) for w in self.width_ratios]

    def head_count(self) -> float:
        """Total height in head-units (1 / head-segment ratio).

        Mirrors vela-nova's estimate: the first segment (head_peak →
        neck_valley) is taken as one head, so ``1 / segment_ratios[0]`` is the
        figure's height in heads. Unstable when head detection is poor — the
        plausibility gate exists precisely to flag the resulting outliers.
        """
        r = self.segment_ratios[0] if self.segment_ratios else 0.0
        return 1.0 / r if r > 1e-9 else float("inf")

    @property
    def vector(self) -> list:
        return list(self.segment_ratios) + list(self.width_ratios)

    def _standardized(self) -> list:
        """Each sub-vector z-scored, so segment and width differences weigh
        equally per standard deviation (ported from ``standardized_vector``)."""
        def z(a: list) -> list:
            if not a:
                return []
            m = sum(a) / len(a)
            sd = max(math.sqrt(sum((x - m) ** 2 for x in a) / len(a)), 1e-9)
            return [(x - m) / sd for x in a]

        return z(self.segment_ratios) + z(self.width_ratios)

    def distance(self, other: "ProportionSignature") -> float:
        """L² distance in standardized proportion space.

        Raises ``ValueError`` on dimensionality mismatch (different landmark
        counts) — two signatures must describe the same landmark set.
        """
        sv, ov = self._standardized(), other._standardized()
        if len(sv) != len(ov):
            raise ValueError(
                f"signature dim mismatch ({len(sv)} vs {len(ov)}): both must "
                f"describe the same landmark set"
            )
        return math.sqrt(sum((a - b) ** 2 for a, b in zip(sv, ov)))

    def to_dict(self) -> dict:
        return {
            "segment_ratios": list(self.segment_ratios),
            "width_ratios": list(self.width_ratios),
            "segment_labels": list(self.segment_labels),
            "landmark_names": list(self.landmark_names),
            "head_count": self.head_count(),
        }


@dataclass
class Landmark:
    """An anatomical landmark on the width profile (head-unit coords)."""

    name: str
    dy: float          # head-units from the crown
    dx: float          # half-width at that height (head-units)
    kind: str = ""     # "peak" | "valley"
    confidence: float = 1.0


# ═══════════════════════════════════════════════════════════════
#  Canon registry (documented classical canons — see module docstring)
# ═══════════════════════════════════════════════════════════════
#  segments: [head, neck-shoulder, torso, pelvis, upper-leg, lower-leg] (head-units)
#  widths:   half-width multiplier at each of the 7 landmarks
_CANON_DEFS: dict[str, tuple[list, list]] = {
    "polykleitos": ([1.0, 0.5, 1.7, 0.8, 1.8, 1.7], [1.0, 1.0, 1.05, 1.1, 1.05, 1.0, 1.0]),
    "vitruvian":   ([1.0, 0.5, 1.8, 0.8, 2.0, 1.9], [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]),
    "heroic":      ([1.0, 0.5, 1.8, 0.8, 2.2, 2.2], [1.05, 1.05, 1.15, 1.1, 1.1, 1.05, 1.0]),
    "fashion":     ([1.0, 0.5, 1.6, 0.7, 2.5, 2.7], [1.0, 0.95, 0.92, 0.9, 0.93, 0.95, 0.95]),
}


def _make_canon(segments: list, widths: list) -> ProportionSignature:
    total = sum(segments)
    seg_ratios = [s / total for s in segments]
    labels = [
        f"{_LANDMARK_NAMES[i]}→{_LANDMARK_NAMES[i + 1]}"
        for i in range(len(segments))
    ]
    return ProportionSignature(seg_ratios, list(widths), labels, list(_LANDMARK_NAMES))


CANONS: dict[str, ProportionSignature] = {
    name: _make_canon(seg, w) for name, (seg, w) in _CANON_DEFS.items()
}


def blend_signatures(
    src: ProportionSignature, tgt: ProportionSignature, alpha: float
) -> ProportionSignature:
    """Lerp two signatures in proportion space (α=0 → src, α=1 → tgt).

    Ported from vela-nova ``proportion.interpolate``. Raises on segment-count
    mismatch.
    """
    if len(src.segment_ratios) != len(tgt.segment_ratios):
        raise ValueError(
            f"segment count mismatch ({len(src.segment_ratios)} vs "
            f"{len(tgt.segment_ratios)})"
        )
    seg = [(1 - alpha) * a + alpha * b for a, b in zip(src.segment_ratios, tgt.segment_ratios)]
    s = sum(seg)
    if s < 1e-12:
        raise ValueError("interpolated segment_ratios sum to ~0 — degenerate inputs")
    seg = [x / s for x in seg]
    wid = [(1 - alpha) * a + alpha * b for a, b in zip(src.width_ratios, tgt.width_ratios)]
    return ProportionSignature(seg, wid, list(src.segment_labels), list(src.landmark_names))


# ═══════════════════════════════════════════════════════════════
#  Width profile + landmark detection (1-D persistence)
# ═══════════════════════════════════════════════════════════════
def width_profile(
    points: Sequence[Point], *, head_count: float = 8.0, n_bins: int = 160
) -> list:
    """Outer half-width at each height level, in head-units.

    Bins the silhouette by y; each bin's value is the max horizontal distance
    from the figure midline (so left/right collapse to a single outer
    profile). Scaled so 1 head = ``fig_height / head_count``. Empty bins
    forward-fill. Returns a list of ``[dx, dy]`` ascending in dy.
    """
    if not points:
        return []
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    midline = (min(xs) + max(xs)) / 2.0
    y_top, y_bot = min(ys), max(ys)
    fig_h = y_bot - y_top
    if fig_h <= 0:
        return []
    scale = head_count / fig_h  # head-units per pixel (= 1 / head_px)
    profile: list = []
    last = 0.0
    for i in range(n_bins):
        blo = y_top + fig_h * i / n_bins
        bhi = y_top + fig_h * (i + 1) / n_bins
        if i == n_bins - 1:
            ext = [abs(x - midline) for x, y in zip(xs, ys) if blo <= y <= bhi]
        else:
            ext = [abs(x - midline) for x, y in zip(xs, ys) if blo <= y < bhi]
        if ext:
            last = max(ext)
        center = (blo + bhi) / 2.0
        profile.append([last * scale, (center - y_top) * scale])
    return profile


def _smooth1d(values: list, k: int) -> list:
    """Centered moving average, window ``k`` (odd), edges shrink — the stdlib
    stand-in for scipy ``uniform_filter1d``."""
    n = len(values)
    if n == 0 or k <= 1:
        return list(values)
    if k % 2 == 0:
        k += 1
    h = k // 2
    out = []
    for i in range(n):
        lo, hi = max(0, i - h), min(n, i + h + 1)
        out.append(sum(values[lo:hi]) / (hi - lo))
    return out


def _std(a: list) -> float:
    if not a:
        return 0.0
    m = sum(a) / len(a)
    return math.sqrt(sum((x - m) ** 2 for x in a) / len(a))


def _persistence_1d(values: list) -> list:
    """0-D persistence pairs of a 1-D function (pure-Python port).

    Returns ``(index, paired_index, persistence, kind)`` tuples, dedup'd to the
    highest-persistence entry per index. Persistence = |Δ value| to the nearest
    opposite-type extremum — the prominence of each peak/valley.
    """
    n = len(values)
    if n < 3:
        return []
    peaks, valleys = [], []
    for i in range(1, n - 1):
        if values[i] > values[i - 1] and values[i] > values[i + 1]:
            peaks.append(i)
        elif values[i] < values[i - 1] and values[i] < values[i + 1]:
            valleys.append(i)
    if values[0] > values[1]:
        peaks.append(0)
    elif values[0] < values[1]:
        valleys.append(0)
    if values[-1] > values[-2]:
        peaks.append(n - 1)
    elif values[-1] < values[-2]:
        valleys.append(n - 1)

    extrema = [(i, "peak", values[i]) for i in peaks] + [
        (i, "valley", values[i]) for i in valleys
    ]
    extrema.sort(key=lambda x: x[0])
    if len(extrema) < 2:
        return []

    pairs = []
    for j, (idx, kind, val) in enumerate(extrema):
        best, best_d = None, float("inf")
        for k2, (oidx, okind, oval) in enumerate(extrema):
            if k2 == j or okind == kind:
                continue
            d = abs(idx - oidx)
            if d < best_d:
                best_d, best = d, (oidx, oval)
        if best is not None:
            pairs.append((idx, best[0], abs(val - best[1]), kind))

    seen, uniq = set(), []
    for idx, paired, pers, kind in sorted(pairs, key=lambda x: -x[2]):
        if idx not in seen:
            seen.add(idx)
            uniq.append((idx, paired, pers, kind))
    return uniq


def _classify(dy: float, kind: str, bands: list) -> Union[str, None]:
    for name, lo, hi, band_kind in bands:
        if band_kind == kind and lo <= dy <= hi:
            return name
    return None


def _extremum_in_band(dxs: list, dy: list, lo: float, hi: float, kind: str):
    idxs = [i for i in range(len(dy)) if lo <= dy[i] <= hi]
    if not idxs:
        return None
    return max(idxs, key=lambda i: dxs[i]) if kind == "peak" else min(idxs, key=lambda i: dxs[i])


def find_landmarks(profile: list, *, extended: bool = False) -> list:
    """Detect anatomical landmarks by 1-D persistence on the width profile.

    Ported from vela-nova ``find_anatomical_landmarks``: persistence finds the
    prominent peaks/valleys (scale-robust), then a band scheme names them by
    dy position, with a band-search fallback for any missing critical
    landmark. ``profile`` is the output of :func:`width_profile`.
    """
    n = len(profile)
    if n < 3:
        return []
    dx = [p[0] for p in profile]
    dy = [p[1] for p in profile]
    kernel = max(9, n // 40)
    dxs = _smooth1d(dx, kernel)
    dx_range = max(dxs) - min(dxs)
    pers_threshold = max(0.02, dx_range * 0.05)

    significant = [
        (idx, pers, kind)
        for idx, _, pers, kind in _persistence_1d(dxs)
        if pers >= pers_threshold
    ]
    significant.sort(key=lambda x: dy[x[0]])

    landmarks: list = []
    assigned: set = set()
    prev = -1.0
    for idx, pers, kind in significant:
        lm_dy = dy[idx]
        if lm_dy < prev + _MIN_LANDMARK_SEP:
            continue
        name = _classify(lm_dy, kind, _BANDS_7)
        if name is None or name in assigned:
            continue
        band = [dxs[i] for i in range(n) if abs(dy[i] - lm_dy) <= 0.5]
        band_std = _std(band) if band else dx_range * 0.1
        confidence = min(1.0, max(0.0, pers / (band_std + 1e-9)))
        landmarks.append(Landmark(name, lm_dy, profile[idx][0], kind, confidence))
        assigned.add(name)
        prev = lm_dy

    # Fallback: fill missing critical landmarks via band search.
    missing = {name for name, _, _, _ in _BANDS_7} - assigned
    for name, lo, hi, kind in _BANDS_7:
        if name not in missing:
            continue
        eff_lo = lo
        for lm in landmarks:
            if lm.dy < lo and lm.dy + _MIN_LANDMARK_SEP > eff_lo:
                eff_lo = lm.dy + _MIN_LANDMARK_SEP
        if eff_lo >= hi:
            continue
        idx = _extremum_in_band(dxs, dy, eff_lo, hi, kind)
        if idx is None:
            continue
        lm_dy = dy[idx]
        if any(abs(lm_dy - lm.dy) < _MIN_LANDMARK_SEP for lm in landmarks):
            continue
        landmarks.append(Landmark(name, lm_dy, profile[idx][0], kind, 0.3))
        assigned.add(name)

    landmarks.sort(key=lambda lm: lm.dy)
    return landmarks


def proportion_signature(landmarks: list) -> ProportionSignature:
    """Build a :class:`ProportionSignature` from ordered landmarks.

    Ported from vela-nova ``extract_signature``. Needs ≥ 2 landmarks spanning
    a positive height.
    """
    if len(landmarks) < 2:
        raise ValueError(f"need >= 2 landmarks, got {len(landmarks)}")
    lm = sorted(landmarks, key=lambda l: l.dy)
    total = lm[-1].dy - lm[0].dy
    if total <= 0:
        raise ValueError(f"landmarks must span a positive height, got {total:.4f}")
    seg, labels = [], []
    for i in range(len(lm) - 1):
        seg.append((lm[i + 1].dy - lm[i].dy) / total)
        labels.append(f"{lm[i].name}→{lm[i + 1].name}")
    widths = [l.dx / total for l in lm]
    return ProportionSignature(seg, widths, labels, [l.name for l in lm])


# ═══════════════════════════════════════════════════════════════
#  Figure model (analyze) + bridges to/from FrameForge objects
# ═══════════════════════════════════════════════════════════════
@dataclass
class FigureFrame:
    """Pixel ↔ head-unit frame for one analyzed figure."""

    midline: float
    y_top: float
    head_px: float


@dataclass
class FigureModel:
    points: list                       # the silhouette polygon (image px)
    frame: FigureFrame
    profile: list                      # width_profile output
    landmarks: list
    signature: Union[ProportionSignature, None]


def _looks_like_objs(source: Sequence) -> bool:
    return bool(source) and isinstance(source[0], dict)


def _bbox_area(pts: Sequence[Point]) -> float:
    xs = [float(p[0]) for p in pts]
    ys = [float(p[1]) for p in pts]
    return (max(xs) - min(xs)) * (max(ys) - min(ys))


def dominant_contour(objs: Sequence[Obj]) -> list:
    """Pick the largest polyline/polygon — the figure silhouette — from objs.

    The realistic input is :func:`frameforge_coach.ingest.ingest`'s region
    polygons; the figure is the one with the largest bounding box. Returns its
    points as ``[[x, y], ...]``.
    """
    best, best_area = None, -1.0
    for o in objs:
        if o.get("type") in _PT_TYPES and o.get("points"):
            area = _bbox_area(o["points"])
            if area > best_area:
                best_area, best = area, o["points"]
    if best is None:
        raise ValueError("no polyline/polygon objects to take a contour from")
    return [[float(p[0]), float(p[1])] for p in best]


def analyze(
    source: Sequence, *, head_count: float = 8.0, n_bins: int = 160, extended: bool = False
) -> FigureModel:
    """Full read of a figure: contour → frame → width profile → landmarks →
    signature.

    ``source`` is either a list of FrameForge objects (the dominant contour is
    taken) or a raw ``[[x, y], ...]`` point list. ``head_count`` is the assumed
    canon used to scale the height into head-units for band naming.
    """
    points = (
        dominant_contour(source)
        if _looks_like_objs(source)
        else [[float(p[0]), float(p[1])] for p in source]
    )
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    fig_h = max(ys) - min(ys)
    frame = FigureFrame(
        midline=(min(xs) + max(xs)) / 2.0,
        y_top=min(ys),
        head_px=(fig_h / head_count) if head_count > 0 else 1.0,
    )
    profile = width_profile(points, head_count=head_count, n_bins=n_bins)
    landmarks = find_landmarks(profile, extended=extended)
    signature = proportion_signature(landmarks) if len(landmarks) >= 2 else None
    return FigureModel(points, frame, profile, landmarks, signature)


def to_polygon_obj(
    points: Sequence[Point], *, fill: str = "#000000", stroke: Union[str, None] = None,
    width: float = 1.0, decorative: bool = False,
) -> Obj:
    """Wrap a point list as a FrameForge ``polygon`` object."""
    obj: Obj = {
        "type": "polygon",
        "points": [[float(p[0]), float(p[1])] for p in points],
        "fill": fill,
    }
    if stroke:
        obj["stroke"] = stroke
        obj["stroke_style"] = {"stroke_width": width}
    if decorative:
        obj["decorative"] = True
    return obj


# ═══════════════════════════════════════════════════════════════
#  Retarget (piecewise-affine) + mirror
# ═══════════════════════════════════════════════════════════════
def _cumulative_dys(top: float, total: float, seg_ratios: list) -> list:
    dys = [top]
    for r in seg_ratios:
        dys.append(dys[-1] + r * total)
    return dys


def remap_dy(dy: float, src_dys: list, tgt_dys: list) -> float:
    """Piecewise-linear remap of one height from source to target breakpoints.

    Landmarks map to landmarks; positions between are linearly interpolated;
    positions outside the span extrapolate from the nearest segment. Ported
    from the dy half of vela-nova ``transform_contour``.
    """
    n = len(src_dys)
    if n < 2:
        return dy
    if dy <= src_dys[0]:
        seg = 0
    elif dy >= src_dys[-1]:
        seg = n - 2
    else:
        seg = max(0, min(bisect.bisect_right(src_dys, dy) - 1, n - 2))
    lo, hi = src_dys[seg], src_dys[seg + 1]
    span = hi - lo
    t = (dy - lo) / span if span > 1e-9 else 0.0
    return tgt_dys[seg] + t * (tgt_dys[seg + 1] - tgt_dys[seg])


def _align_to(src: ProportionSignature, tgt: ProportionSignature) -> ProportionSignature:
    """Re-express ``tgt`` over ``src``'s detected landmark set, by name.

    Detection may find fewer than 7 landmarks; this maps each src segment to
    the target canon's cumulative position of the same named endpoints, so the
    retarget never fails on a count mismatch. Missing names fall back to an
    even split / the source's own width.
    """
    if src.landmark_names == tgt.landmark_names:
        return tgt
    tgt_cum = {tgt.landmark_names[0]: 0.0}
    acc = 0.0
    for i, r in enumerate(tgt.segment_ratios):
        acc += r
        tgt_cum[tgt.landmark_names[i + 1]] = acc

    names = src.landmark_names
    m = len(names)
    pos = [tgt_cum.get(nm) for nm in names]
    for i in range(m):
        if pos[i] is None:
            pos[i] = i / (m - 1) if m > 1 else 0.0
    for i in range(1, m):  # enforce strictly increasing
        if pos[i] <= pos[i - 1]:
            pos[i] = pos[i - 1] + 1e-3
    seg = [pos[i + 1] - pos[i] for i in range(m - 1)]
    s = sum(seg)
    seg = [x / s for x in seg] if s > 1e-9 else seg
    tgt_w = dict(zip(tgt.landmark_names, tgt.width_ratios))
    wid = [
        tgt_w.get(nm, src.width_ratios[i] if i < len(src.width_ratios) else 1.0)
        for i, nm in enumerate(names)
    ]
    return ProportionSignature(seg, wid, list(src.segment_labels), list(names))


def _width_scale(dyhu: float, lm_dys: list, src_w: list, tgt_w: list) -> float:
    n = len(lm_dys)
    if n < 2 or len(src_w) != n or len(tgt_w) != n:
        return 1.0
    if dyhu <= lm_dys[0]:
        i, t = 0, 0.0
    elif dyhu >= lm_dys[-1]:
        i, t = n - 2, 1.0
    else:
        i = max(0, min(bisect.bisect_right(lm_dys, dyhu) - 1, n - 2))
        span = lm_dys[i + 1] - lm_dys[i]
        t = (dyhu - lm_dys[i]) / span if span > 1e-9 else 0.0
    sw = (1 - t) * src_w[i] + t * src_w[i + 1]
    tw = (1 - t) * tgt_w[i] + t * tgt_w[i + 1]
    return tw / sw if sw > 1e-9 else 1.0


def retarget(
    model: FigureModel,
    canon: Union[str, ProportionSignature],
    *,
    points: Union[Sequence[Point], None] = None,
    scale_widths: bool = False,
) -> list:
    """Retarget a figure's proportions onto ``canon`` (piecewise-affine).

    Total height is preserved exactly (the crown/sole extremes are anchored);
    interior segments redistribute toward the canon. ``canon`` is a registered
    name (e.g. ``"fashion"``) or an explicit :class:`ProportionSignature`.

    By default the model's own silhouette points are transformed. Pass
    ``points`` to transform any other geometry — e.g. one ingested line-art
    stroke — in the *same* figure frame, so a whole drawing re-proportions
    consistently. Returns transformed image-coord points, one per input point.
    Optionally rescales widths toward the canon's build.
    """
    if model.signature is None:
        raise ValueError("model has no signature (need >= 2 landmarks) to retarget")
    src = model.signature
    tgt = canon if isinstance(canon, ProportionSignature) else CANONS.get(canon)
    if tgt is None:
        raise ValueError(f"unknown canon {canon!r}; known: {sorted(CANONS)}")
    tgt = _align_to(src, tgt)

    lm = sorted(model.landmarks, key=lambda l: l.dy)
    top = lm[0].dy
    total = lm[-1].dy - lm[0].dy
    src_dys = _cumulative_dys(top, total, src.segment_ratios)
    tgt_dys = _cumulative_dys(top, total, tgt.segment_ratios)

    fr = model.frame
    # Anchors come from the whole figure's extent (global frame), so any passed
    # geometry remaps consistently with the silhouette.
    dyhu_global = [(p[1] - fr.y_top) / fr.head_px for p in model.points]
    y_min, y_max = min(dyhu_global), max(dyhu_global)
    src_anchored, tgt_anchored = list(src_dys), list(tgt_dys)
    if y_min < src_dys[0]:  # anchor crown so total height is preserved exactly
        src_anchored = [y_min] + src_anchored
        tgt_anchored = [y_min] + tgt_anchored
    if y_max > src_dys[-1]:  # anchor sole
        src_anchored = src_anchored + [y_max]
        tgt_anchored = tgt_anchored + [y_max]

    target = model.points if points is None else points
    out = []
    for p in target:
        x, y = float(p[0]), float(p[1])
        dyhu = (y - fr.y_top) / fr.head_px
        ndy = remap_dy(dyhu, src_anchored, tgt_anchored)
        dxhu = (x - fr.midline) / fr.head_px
        if scale_widths:
            dxhu *= _width_scale(dyhu, src_dys, src.width_ratios, tgt.width_ratios)
        out.append([fr.midline + dxhu * fr.head_px, fr.y_top + ndy * fr.head_px])
    return out


def _span(pts: list, midline: float) -> float:
    return max((abs(p[0] - midline) for p in pts), default=0.0)


def mirror_outer(points: Sequence[Point], *, midline: Union[float, None] = None) -> list:
    """Rebuild a bilaterally symmetric figure from its wider half.

    Keeps the side of ``midline`` with the larger extent (the "outer" half) and
    reflects it to the other side — the pure-geometry analogue of vela-nova's
    ``_body_mask_from_contour`` mirror. Returns a closed point loop.
    """
    pts = [[float(p[0]), float(p[1])] for p in points]
    xs = [p[0] for p in pts]
    if midline is None:
        midline = (min(xs) + max(xs)) / 2.0
    right = [p for p in pts if p[0] >= midline]
    left = [p for p in pts if p[0] < midline]
    outer = right if _span(right, midline) >= _span(left, midline) else left
    reflected = [[2 * midline - p[0], p[1]] for p in outer]
    return [list(p) for p in outer] + list(reversed(reflected))


# ═══════════════════════════════════════════════════════════════
#  Advisory plausibility gate (PALS's Law: advisory, not a guarantee)
# ═══════════════════════════════════════════════════════════════
def plausibility(
    signature: ProportionSignature,
    *,
    references: Union[Sequence[ProportionSignature], None] = None,
    head_count_range: tuple = (6.0, 11.0),
    min_segment_ratio: float = 0.03,
    min_width_ratio: float = 0.0005,
) -> dict:
    """Advisory anatomical sanity check on a proportion signature.

    Flags the extraction failures the proportion algebra would otherwise
    amplify: an implausible head count, a collapsed (near-zero) segment from a
    missed landmark, or a zero-width landmark. Ranges are the documented canon
    bounds (~6-11 heads spans Polykleitos through fashion). When ``references``
    are supplied, attaches the minimum standardized distance to that set as an
    *advisory* signal — never a hard verdict.

    Returns ``{"plausible": bool, "issues": [...], "head_count": float,
    "advisory": True, ["reference_distance": float|None]}``. This is a sanity
    check, not a fidelity guarantee — see the module contract.
    """
    issues: list = []
    hc = signature.head_count()
    lo, hi = head_count_range
    if not (lo <= hc <= hi):
        issues.append(
            f"head_count {hc:.2f} outside documented canon range [{lo}, {hi}]"
        )
    seg_sum = sum(signature.segment_ratios)
    if abs(seg_sum - 1.0) > 0.02:
        issues.append(f"segment_ratios sum to {seg_sum:.4f}, expected 1.0")
    for i, r in enumerate(signature.segment_ratios):
        if r < min_segment_ratio:
            label = (
                signature.segment_labels[i]
                if i < len(signature.segment_labels)
                else f"segment[{i}]"
            )
            issues.append(
                f"segment '{label}' ratio {r:.4f} < {min_segment_ratio} "
                f"(too short — likely a missed landmark)"
            )
    for i, w in enumerate(signature.width_ratios):
        if w < min_width_ratio:
            name = (
                signature.landmark_names[i]
                if i < len(signature.landmark_names)
                else f"width[{i}]"
            )
            issues.append(
                f"width '{name}' = {w:.4f} (zero-width landmark — extraction failure)"
            )

    report: dict = {
        "plausible": not issues,
        "issues": issues,
        "head_count": hc,
        "advisory": True,
    }
    if references:
        try:
            report["reference_distance"] = min(
                signature.distance(r) for r in references
            )
        except ValueError:
            report["reference_distance"] = None
    return report


__all__ = [
    "ProportionSignature",
    "Landmark",
    "FigureFrame",
    "FigureModel",
    "CANONS",
    "blend_signatures",
    "width_profile",
    "find_landmarks",
    "proportion_signature",
    "dominant_contour",
    "analyze",
    "to_polygon_obj",
    "remap_dy",
    "retarget",
    "mirror_outer",
    "plausibility",
]
