"""Off-screen renders of the assembly and of individual parts."""

import numpy as np
import pyvista as pv
from manifold3d import Manifold

pv.OFF_SCREEN = True
COLOURS = {"base": "#3b6ea5", "lever": "#e08a2e", "upper": "#e8e4d8", "lower": "#cfd8dc", "screw": "#7a8c3a", "nut": "#7a8c3a", "pin": "#444444", "pad": "#c0504d", "template": "#6b8e9e"}


def to_polydata(solid: Manifold) -> pv.PolyData:
    mesh = solid.to_mesh()
    faces = np.hstack([np.full((len(mesh.tri_verts), 1), 3), mesh.tri_verts]).astype(np.int64)
    return pv.PolyData(np.asarray(mesh.vert_properties)[:, :3].astype(float), faces)


def render(solids: dict[str, Manifold], path: str, view: str = "side", size=(1400, 1000), zoom: float = 1.25, clip_y: float | None = None, focus=None, camera=None):
    """focus = (x, z, visible_height_mm) frames a detail in the side view."""
    plotter = pv.Plotter(off_screen=True, window_size=size)
    plotter.set_background("white")
    for name, solid in solids.items():
        data = to_polydata(solid)
        if clip_y is not None:
            data = data.clip(normal=(0, 1, 0), origin=(0, clip_y, 0), invert=False)
        colour = next((c for key, c in COLOURS.items() if name.startswith(key)), "#999999")
        plotter.add_mesh(data, color=colour, smooth_shading=False, split_sharp_edges=True, specular=0.2)
    if view == "side":
        bounds = np.array([to_polydata(s).bounds for s in solids.values()])
        cx, cz = (bounds[:, 0].min() + bounds[:, 1].max()) / 2, (bounds[:, 4].min() + bounds[:, 5].max()) / 2
        plotter.camera_position = [(cx, -1000, cz), (cx, 0, cz), (0, 0, 1)]
        plotter.enable_parallel_projection()
        plotter.reset_camera()
        if focus is not None:
            plotter.camera_position = [(focus[0], -1000, focus[1]), (focus[0], 0, focus[1]), (0, 0, 1)]
            plotter.camera.parallel_scale = focus[2] / 2
            zoom = 1.0
    elif view == "iso":
        plotter.camera_position = [(-260, -330, 190), (70, 0, -60), (0, 0, 1)]
    elif view == "front":
        plotter.camera_position = [(-330, -120, 60), (40, 0, -40), (0, 0, 1)]
    elif view == "top":
        plotter.view_xy()
        plotter.enable_parallel_projection()
    if camera is not None:
        plotter.camera_position = camera
        plotter.camera.view_angle = 22
    plotter.camera.zoom(zoom)
    plotter.screenshot(path)
    plotter.close()
