"""Small 2D/3D geometry helpers on top of shapely (2D) and manifold3d (3D)."""

import numpy as np
import shapely
import shapely.affinity
from manifold3d import CrossSection, Manifold
from matplotlib.font_manager import FontProperties
from matplotlib.textpath import TextPath
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import unary_union

ARC_TOLERANCE_MM = 0.02
CIRCLE_SEGMENTS = 96


def circle(centre, radius: float) -> Polygon:
    return Point(*centre).buffer(radius, quad_segs=CIRCLE_SEGMENTS // 4)


def polygon(points) -> Polygon:
    return Polygon(points).buffer(0)


def capsule(start, end, width: float) -> Polygon:
    return LineString([start, end]).buffer(width / 2, quad_segs=CIRCLE_SEGMENTS // 4)


def ring_sector(centre, inner_radius, outer_radius, start_deg, end_deg, step_deg=2.0) -> Polygon:
    angles = np.radians(np.arange(start_deg, end_deg + step_deg / 2, step_deg))
    outer = [(centre[0] + outer_radius * np.cos(a), centre[1] + outer_radius * np.sin(a)) for a in angles]
    inner = [(centre[0] + inner_radius * np.cos(a), centre[1] + inner_radius * np.sin(a)) for a in angles[::-1]]
    return polygon(outer + inner)


def rounded(shape, convex_radius: float = 0.0, concave_radius: float = 0.0):
    """Round outward corners by convex_radius and inward corners by concave_radius."""
    if concave_radius:
        shape = shape.buffer(concave_radius, quad_segs=16).buffer(-concave_radius, quad_segs=16)
    if convex_radius:
        shape = shape.buffer(-convex_radius, quad_segs=16).buffer(convex_radius, quad_segs=16)
    return shape


def rotated(shape, angle_rad: float, centre):
    return shapely.affinity.rotate(shape, angle_rad, origin=tuple(centre), use_radians=True)


def text_shape(text: str, height_mm: float, bold: bool = True):
    """Text as a shapely geometry, lower-left corner of its bounding box at the origin."""
    path = TextPath((0, 0), text, size=height_mm * 1.39, prop=FontProperties(family="DejaVu Sans", weight="bold" if bold else "normal"))
    rings = [Polygon(ring) for ring in path.to_polygons() if len(ring) >= 4]
    glyphs = None
    for ring in sorted(rings, key=lambda r: -r.area):  # holes are the smaller rings inside
        ring = ring.buffer(0)
        if glyphs is None:
            glyphs = ring
        elif glyphs.contains(ring.representative_point()):
            glyphs = glyphs.difference(ring)
        else:
            glyphs = glyphs.union(ring)
    min_x, min_y, _, _ = glyphs.bounds
    return shapely.affinity.translate(glyphs, -min_x, -min_y)


def _polygons(shape):
    if shape.is_empty:
        return []
    if isinstance(shape, Polygon):
        return [shape]
    if isinstance(shape, MultiPolygon):
        return list(shape.geoms)
    return [g for g in shape.geoms if isinstance(g, Polygon)]


def cross_section(shape) -> CrossSection:
    contours = []
    for poly in _polygons(shape.simplify(ARC_TOLERANCE_MM)):
        poly = shapely.geometry.polygon.orient(poly)
        contours.append(np.asarray(poly.exterior.coords)[:-1])
        contours.extend(np.asarray(hole.coords)[:-1] for hole in poly.interiors)
    return CrossSection(contours)


def extrude(shape, z_min: float, z_max: float) -> Manifold:
    return cross_section(shape).extrude(z_max - z_min).translate((0, 0, z_min))


def extrude_chamfered(shape, z_min: float, z_max: float, chamfer: float, layer: float = 0.2) -> Manifold:
    """Extrude with 45-degree chamfers on both faces, built as layer-height steps."""
    steps = int(round(chamfer / layer))
    solids = [extrude(shape, z_min + chamfer, z_max - chamfer)]
    for i in range(steps):
        inset = shape.buffer(-(chamfer - i * layer), quad_segs=8)
        solids.append(extrude(inset, z_min + i * layer, z_min + (i + 1) * layer))
        solids.append(extrude(inset, z_max - (i + 1) * layer, z_max - i * layer))
    return Manifold.batch_boolean(solids, _ADD)


def cylinder_z(centre_xy, radius: float, z_min: float, z_max: float) -> Manifold:
    return Manifold.cylinder(z_max - z_min, radius, radius, CIRCLE_SEGMENTS).translate((centre_xy[0], centre_xy[1], z_min))


def box(x_range, y_range, z_range) -> Manifold:
    size = (x_range[1] - x_range[0], y_range[1] - y_range[0], z_range[1] - z_range[0])
    return Manifold.cube(size).translate((x_range[0], y_range[0], z_range[0]))


def union(solids) -> Manifold:
    return Manifold.batch_boolean(list(solids), _ADD)


def union_2d(shapes):
    return unary_union(list(shapes))


def _op_add():
    import manifold3d

    return manifold3d.OpType.Add


_ADD = _op_add()
