"""Build every part, verify the assembly, and write STLs, renders and a numeric report."""

import pathlib

import numpy as np
import shapely
import trimesh
from manifold3d import Manifold

import geom
import parts
from assembly import Assembly, about_lateral_axis
from design import DESIGN as d
from render import render

ROOT = pathlib.Path(__file__).parent
STL_DIR, IMAGE_DIR = ROOT / "stl", ROOT / "docs" / "images"
BED_MM = 250.0


def to_trimesh(solid: Manifold) -> trimesh.Trimesh:
    mesh = solid.to_mesh()
    return trimesh.Trimesh(vertices=np.asarray(mesh.vert_properties)[:, :3], faces=np.asarray(mesh.tri_verts), process=False)


def laid_out_for_printing(solid: Manifold) -> Manifold:
    """Turn about Z so the footprint is as compact as possible, then sit it on the bed at the origin."""
    mesh = solid.to_mesh()
    footprint = shapely.MultiPoint(np.asarray(mesh.vert_properties)[:, :2]).minimum_rotated_rectangle
    corners = np.asarray(footprint.exterior.coords)
    edges = np.diff(corners[:3], axis=0)
    longest = edges[np.argmax(np.linalg.norm(edges, axis=1))]
    turned = solid.rotate((0, 0, -np.degrees(np.arctan2(longest[1], longest[0]))))
    x_min, y_min, z_min, x_max, y_max, _ = turned.bounding_box()
    return turned.translate((-(x_min + x_max) / 2, -(y_min + y_max) / 2, -z_min))


def printable_parts() -> dict[str, Manifold]:
    return {
        "base": parts.base(d),
        "lever": parts.lever(d),
        "upper_mouthpiece": parts.upper_mouthpiece(d),
        "lower_tray": parts.lower_tray(d).rotate((180, 0, 0)),  # hinge side on the bed, rims up
        "limit_screw": parts.limit_screw(d),
        "limit_nut": parts.limit_nut(d),
        "pivot_pin_print_2": parts.snap_pin(d.base_width_mm, d),
        "pad_templates": parts.pad_templates(d),
    }


def export_stls(report: list[str]) -> dict[str, Manifold]:
    STL_DIR.mkdir(exist_ok=True)
    laid_out = {name: laid_out_for_printing(solid) for name, solid in printable_parts().items()}
    report.append("Printable parts (as laid on the bed):")
    for name, solid in laid_out.items():
        mesh = to_trimesh(solid)
        assert mesh.is_watertight, name
        mesh.export(STL_DIR / f"{name}.stl")
        size = mesh.extents
        assert max(size[:2]) <= BED_MM, (name, size)
        report.append(f"  {name:20s} {size[0]:6.1f} x {size[1]:5.1f} x {size[2]:5.1f} mm   {solid.volume() / 1000:5.1f} cm3 solid")
    return laid_out


def check_assembly(assembly: Assembly, report: list[str]):
    grip_mm = 85.0
    report.append(f"\nHand force = {d.lever_length_mm / grip_mm:.2f} x force on the teeth (hand {grip_mm:.0f} mm from the pivot)")
    for opening in (d.closed_opening_mm, 20, 30, 40, d.max_opening_mm):
        remaining = d.max_lever_rotation_rad - d.lever_rotation_rad(opening)
        gap = d.handle_gap_at_max_opening_mm + grip_mm * np.tan(remaining)
        report.append(f"  handle gap at the grip, opening {opening:4.1f} mm: {gap:4.1f} mm (grip span {gap + d.base_handle_depth_mm + d.lever_depth_mm:4.1f} mm)")
    report.append(f"\nMain pivot at x = {d.pivot_xz[0]:.1f}, z = {d.pivot_xz[1]:.1f} mm from the upper incisal edge")
    report.append(f"Scale reads {d.closed_opening_mm:.1f} mm fully closed, {d.max_opening_mm:.0f} mm at the hard stop")
    report.append("\nopening  lever turn  tray tilt  path error  interference")
    for opening in [d.closed_opening_mm, *range(14, int(d.max_opening_mm) + 1, 4)]:
        worst = max(assembly.interference_mm3(opening).values())
        hardware = {**assembly.posed(opening), **assembly.hardware(max(opening, 14))}
        names = list(hardware)
        worst = max([worst] + [(hardware[a] ^ hardware[b]).volume() for i, a in enumerate(names) for b in names[i + 1 :]])
        assert worst < 0.05, (opening, worst)
        report.append(
            f"{opening:6.1f}   {np.degrees(d.lever_rotation_rad(opening)):6.1f} deg {np.degrees(d.tray_tilt_rad(opening)):6.1f} deg"
            f" {d.path_error_mm(opening):7.2f} mm  {worst:6.3f} mm3"
        )


def check_thread(report: list[str]):
    """The nut must screw onto the limit screw, and the handedness must be the one set in design.py."""
    screw = parts.limit_screw(d)
    # one whole number of pitches above where the screw's thread starts, the threads are in phase
    meshed = parts.limit_nut(d).translate((0, 0, parts.SCREW_KNOB_HEIGHT_MM + 1 + 4 * d.thread_pitch_mm))
    assert (screw ^ meshed).volume() < 1.5  # mm3; faceting alone gives ~0.7, a thread out of phase ~80
    # crest direction a quarter pitch up the thread: -90 deg for a left-handed thread, +90 for right-handed
    quarter_up = parts.SCREW_KNOB_HEIGHT_MM + 10 * d.thread_pitch_mm + d.thread_pitch_mm / 4
    section = np.vstack(screw.slice(quarter_up).to_polygons())
    crest = section[np.argmax(np.linalg.norm(section, axis=1))]
    crest_deg = np.degrees(np.arctan2(crest[1], crest[0]))
    assert abs(crest_deg - (-90 if d.thread_is_left_handed else 90)) < 20, crest_deg  # the crest has a flat
    hand = "left" if d.thread_is_left_handed else "right"
    report.append(f"\nLimit screw: {hand}-handed thread; nut radial clearance {d.nut_thread_radial_clearance_mm:.2f} mm")


def check_hinge_retention(assembly: Assembly, report: list[str]):
    """The tray must stay hooked at every working tilt and come off only when folded right back."""
    hinge, hinge_in_tray = d.closed_hinge_xz, d.hinge_in_tray_xz
    out = np.array([np.cos(np.radians(d.hook_mouth_direction_deg)), np.sin(np.radians(d.hook_mouth_direction_deg))])

    def comes_off(tilt_deg: float) -> bool:
        for step in np.arange(0, 12.01, 0.25):
            shift = hinge - hinge_in_tray + step * out
            tray = about_lateral_axis(assembly.lower_tray, hinge_in_tray, -np.radians(tilt_deg)).translate((shift[0], 0, shift[1]))
            if (tray ^ assembly.lever_closed).volume() > 0.02:
                return False
        return True

    releasing = [tilt for tilt in range(0, 200, 5) if comes_off(tilt)]
    working_max = np.degrees(d.tray_tilt_rad(d.max_opening_mm) + d.max_lever_rotation_rad)
    assert releasing and min(releasing) > working_max + 30, (releasing, working_max)
    report.append(f"\nLower tray hinge: working tilt up to {working_max:.0f} deg relative to the lever tip; comes off only at {min(releasing)}-{max(releasing)} deg")


def write_renders(assembly: Assembly, laid_out: dict[str, Manifold]):
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    for opening in (d.closed_opening_mm, 30.0, d.max_opening_mm):
        scene = {**assembly.posed(opening), **assembly.hardware(max(opening, 14))}
        tag = "closed" if opening == d.closed_opening_mm else f"{opening:.0f}mm"
        render(scene, str(IMAGE_DIR / f"section_{tag}.png"), "side", clip_y=0.01)
    _write_sections_overview()
    scene = {**assembly.posed(30.0), **assembly.hardware(30.0)}
    render(scene, str(IMAGE_DIR / "assembly_30mm.png"), "iso")
    handle_end = d.pivot_xz + 118 * d.base_handle_direction
    render(scene, str(IMAGE_DIR / "scale_and_limit_screw.png"), "iso", zoom=1.0, camera=[(handle_end[0] + 30, -170, handle_end[1] - 10), (handle_end[0] - 12, 0, handle_end[1] + 4), (0, 0, 1)])
    closed = {**assembly.posed(d.closed_opening_mm), **assembly.hardware(14)}
    render(closed, str(IMAGE_DIR / "mouth_end_closed_section.png"), "side", clip_y=0.01, focus=(8, -4, 52), size=(1500, 900))
    wide = {**assembly.posed(d.max_opening_mm), **assembly.hardware(d.max_opening_mm)}
    render(wide, str(IMAGE_DIR / "mouth_end_46mm_section.png"), "side", clip_y=0.01, focus=(2, -22, 80), size=(1500, 900))
    _write_tray_fitting(assembly)
    _write_pads()
    # the printable parts spread out, seen from above
    spread, x = {}, 0.0
    for name, solid in laid_out.items():
        if name == "pad_templates":  # optional, shown with the pads instead
            continue
        x_min, y_min, _, x_max, y_max, _ = solid.bounding_box()
        key = {"base": "base", "lever": "lever", "upper_mouthpiece": "upper", "lower_tray": "lower", "limit_screw": "screw"}.get(name, "nut" if name == "limit_nut" else "pin")
        spread[f"{key}_{name}"] = solid.rotate((0, 0, 90)).translate((x + (y_max - y_min) / 2, 0, 0))
        x += (y_max - y_min) + 8
    render(spread, str(IMAGE_DIR / "print_layout.png"), "top", size=(1600, 1100), zoom=1.3)
    _trim_margins(IMAGE_DIR / "print_layout.png")


def _trim_margins(path: pathlib.Path, margin_px: int = 50):
    from PIL import Image, ImageChops

    image = Image.open(path).convert("RGB")
    left, top, right, bottom = ImageChops.difference(image, Image.new("RGB", image.size, "white")).getbbox()
    image.crop((max(left - margin_px, 0), max(top - margin_px, 0), min(right + margin_px, image.width), min(bottom + margin_px, image.height))).save(path)


def _write_tray_fitting(assembly: Assembly):
    """The lower tray folded back as it is hooked onto the lever tip, beside its working position."""
    hinge, hinge_in_tray = d.closed_hinge_xz, d.hinge_in_tray_xz
    out = np.array([np.cos(np.radians(d.hook_mouth_direction_deg)), np.sin(np.radians(d.hook_mouth_direction_deg))])
    for name, tilt_deg, slide_mm in (("tray_fitting_1_hook_on", d.tray_fitting_tilt_deg, 7.0), ("tray_fitting_2_swing_forward", 25.0, 0.0)):
        shift = hinge - hinge_in_tray + slide_mm * out
        tray = about_lateral_axis(assembly.lower_tray, hinge_in_tray, -np.radians(tilt_deg)).translate((shift[0], 0, shift[1]))
        render({"lever": assembly.lever_closed, "lower": tray}, str(IMAGE_DIR / f"{name}.png"), "iso", size=(1100, 800), zoom=1.0, camera=[(hinge[0] - 95, -120, hinge[1] + 70), (hinge[0] + 8, 0, hinge[1] - 4), (0, 0, 1)])


def _write_pads(pad_thickness_mm: float = 1.5):
    """Both trays, rims up, with a pad in the tooth channel and the template it is cut round in front."""
    pads = {letter: geom.extrude(shape, 0, pad_thickness_mm) for letter, shape in parts.tooth_pad_shapes(d).items()}
    trays = {"U": ("upper", parts.upper_mouthpiece(d)), "L": ("lower", parts.lower_tray(d).rotate((180, 0, 0)))}
    scene, pitch_mm = {}, 66.0
    for i, (letter, (colour_key, tray)) in enumerate(trays.items()):
        y = -i * pitch_mm
        scene[f"{colour_key}_{letter}"] = tray.translate((0, y, 0))
        scene[f"pad_{letter}"] = pads[letter].translate((0, y, 0))
        scene[f"template_{letter}"] = parts.pad_template(letter, d).translate((-42, y, 0))
    centre = (-12, -pitch_mm / 2, 0)
    render(scene, str(IMAGE_DIR / "pads.png"), "iso", size=(1600, 1300), zoom=1.0, camera=[(centre[0] - 165, centre[1], 320), centre, (1, 0, 0)])
    _trim_margins(IMAGE_DIR / "pads.png")


def _write_sections_overview():
    from PIL import Image, ImageChops, ImageDraw, ImageFont

    titles = {"closed": f"Closed ({d.closed_opening_mm:.1f} mm)", "30mm": "30 mm, limit set to 30", "46mm": "46 mm (hard stop)"}
    panels = []
    for tag in titles:
        panel = Image.open(IMAGE_DIR / f"section_{tag}.png").convert("RGB")
        content = ImageChops.difference(panel, Image.new("RGB", panel.size, "white")).getbbox()
        panels.append(panel.crop(content))
    gap, title_height = 60, 80
    height = max(panel.height for panel in panels)
    width = sum(panel.width for panel in panels) + gap * (len(panels) + 1)
    overview = Image.new("RGB", (width, height + title_height + gap), "white")
    draw = ImageDraw.Draw(overview)
    font = ImageFont.truetype(_font_path(), 40)
    x = gap
    for panel, title in zip(panels, titles.values()):
        overview.paste(panel, (x, title_height + (height - panel.height) // 2))
        draw.text((x + panel.width / 2, title_height / 2 + 10), title, fill="#1f2430", font=font, anchor="mm")
        x += panel.width + gap
    overview.save(IMAGE_DIR / "sections_overview.png")


def _font_path() -> str:
    from matplotlib import font_manager

    return font_manager.findfont("DejaVu Sans")


def main():
    report: list[str] = []
    laid_out = export_stls(report)
    assembly = Assembly(d)
    check_assembly(assembly, report)
    check_hinge_retention(assembly, report)
    check_thread(report)
    (ROOT / "report.txt").write_text("\n".join(report) + "\n")
    print("\n".join(report))
    write_renders(assembly, laid_out)


if __name__ == "__main__":
    main()
