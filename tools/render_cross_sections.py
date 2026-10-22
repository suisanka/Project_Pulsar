"""Plot sagittal and horizontal sections from evaluated front/rear shell meshes.

Extract without saving or changing the source .blend:
  blender -b --factory-startup --disable-autoexec ProjectPulsar_Base.blend \
    --python tools/render_cross_sections.py -- --output /tmp/pulsar-sections.json

Draw with a Python environment containing Pillow:
  python tools/render_cross_sections.py --draw /tmp/pulsar-sections.json \
    --output docs/images --font /path/to/a/CJK-font.ttc

The plot shows material intersected by each plane, not a projection or a
manufacturing drawing. All geometry coordinates and measurements are in mm.
"""

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path


SHELLS = ("前壳配置", "后壳配置")
COLORS = ("#317DA1", "#D69546")
LEVELS = (-40.0, 0.0, 60.0)


def contours(vertices, faces, axis, height):
    """Intersect triangles with a plane and require closed, unbranched contours."""
    import numpy as np

    points = vertices[faces]
    distances = points[:, :, axis] - height
    crosses = ((distances >= 0).any(axis=1)
               & (distances < 0).any(axis=1))
    points, distances = points[crosses], distances[crosses]
    hits = [[] for _ in range(len(points))]
    axes = [a for a in range(3) if a != axis]
    for a, b in ((0, 1), (1, 2), (2, 0)):
        selected = np.flatnonzero((distances[:, a] >= 0) != (distances[:, b] >= 0))
        fraction = distances[selected, a] / (distances[selected, a] - distances[selected, b])
        xyz = points[selected, a] + fraction[:, None] * (points[selected, b] - points[selected, a])
        for index, point in zip(selected, xyz):
            hits[index].append(tuple(round(float(point[a]), 5) for a in axes))
    edges = {tuple(sorted(pair)) for pair in hits if len(pair) == 2 and pair[0] != pair[1]}
    adjacency = defaultdict(set)
    for a, b in edges:
        adjacency[a].add(b)
        adjacency[b].add(a)
    bad = {p: len(v) for p, v in adjacency.items() if len(v) != 2}
    if bad:
        raise ValueError(f"Plane {axis}={height}: {len(bad)} open/branching contour vertices")
    loops = []
    while edges:
        start, current = min(edges)
        previous = start
        loop = [start]
        edges.remove(tuple(sorted((start, current))))
        while current != start:
            loop.append(current)
            following = next(p for p in adjacency[current] if p != previous)
            edges.remove(tuple(sorted((current, following))))
            previous, current = current, following
        if len(loop) >= 3:
            loops.append(loop)
    return sorted(loops, key=lambda loop: (-len(loop), loop[0]))


def extract(args):
    import bpy
    import numpy as np

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from hinge_common import arrays
    from validate_model import triangle_metrics

    source = Path(bpy.data.filepath)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    record = {
        "source": source.name, "source_sha256": digest,
        "blender": bpy.app.version_string, "units": "mm",
        "view": "from +Z toward -Z; +Y (face) at top; +X at right",
        "join_precision_mm": 0.00001, "objects": [], "sections": [],
        "limitations": "Shell material only; excludes separate hardware, padding and wearer. Z is the original model coordinate, not height above the chin.",
    }
    meshes = []
    for name in SHELLS:
        vertices, faces = arrays(name)
        metrics = triangle_metrics(vertices, faces)
        for key in ("boundary_edges", "multi_face_edges", "inconsistent_edges", "duplicate_triangles", "degenerate_triangles"):
            if metrics[key]:
                raise ValueError(f"{name}: {key}={metrics[key]}")
        meshes.append((vertices, faces))
        record["objects"].append({"name": name, "metrics": metrics,
                                   "bounds_mm": [vertices.min(0).tolist(), vertices.max(0).tolist()]})
    for height in LEVELS:
        outlines = [contours(v, f, 2, height) for v, f in meshes]
        points = np.array([p for loops in outlines for loop in loops for p in loop])
        record["sections"].append({"z_mm": height, "outlines": outlines,
                                   "bounds_mm": [points.min(0).tolist(), points.max(0).tolist()],
                                   "outer_span_mm": np.ptp(points, axis=0).tolist(),
                                   "closed_loops": [len(loops) for loops in outlines]})
    record["side_section"] = [contours(v, f, 0, 0.0) for v, f in meshes]
    if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
        raise RuntimeError("Source file changed during extraction")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"source_sha256": digest, "triangles": [o["metrics"]["triangles"] for o in record["objects"]],
                      "sections": [{k: v for k, v in s.items() if k != "outlines"} for s in record["sections"]]}, ensure_ascii=False), flush=True)


def draw(args):
    from PIL import Image, ImageChops, ImageDraw, ImageFont

    data = json.loads(args.draw.read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    font_path = args.font
    scale = 2
    ink, muted, grid = "#203746", "#647887", "#E3E9EC"

    def new_canvas(width, height):
        im = Image.new("RGB", (width * scale, height * scale), "#F8FAFB")
        return im, ImageDraw.Draw(im)

    def text(painter, xy, value, size=22, color=ink, anchor=None):
        painter.text(tuple(c * scale for c in xy), value, fill=color,
                     font=ImageFont.truetype(str(font_path), size * scale), anchor=anchor)

    def line(painter, coords, color=grid, width=1):
        painter.line([(int(x * scale), int(y * scale)) for x, y in coords], fill=color, width=width * scale)

    def material(im, outlines, transform):
        for loops, color in zip(outlines, COLORS):
            mask = Image.new("1", im.size, 0)
            for loop in loops:
                layer = Image.new("1", im.size, 0)
                ImageDraw.Draw(layer).polygon([(round(x * scale), round(y * scale)) for x, y in map(transform, loop)], fill=1)
                mask = ImageChops.logical_xor(mask, layer)
            im.paste(color, mask=mask)

    def section_plot(im, painter, section, center, factor):
        cx, cy = center
        transform = lambda p: (cx + p[0] * factor, cy - p[1] * factor)
        extent = 140
        for mm in range(-120, 121, 20):
            line(painter, [transform((mm, -extent)), transform((mm, extent))])
            line(painter, [transform((-extent, mm)), transform((extent, mm))])
        line(painter, [transform((-extent, 0)), transform((extent, 0))], "#B9C8D0")
        line(painter, [transform((0, -extent)), transform((0, extent))], "#B9C8D0")
        material(im, section["outlines"], transform)
        text(painter, (cx, cy - extent * factor - 14), "前 / 面部  +Y", 18, anchor="mb")
        text(painter, (cx, cy + extent * factor + 14), "后 / 后脑  -Y", 18, anchor="mt")

    def legend(painter, xy):
        x, y = xy
        for name, color in zip(("前壳", "后壳"), COLORS):
            painter.rounded_rectangle((x * scale, y * scale, (x + 22) * scale, (y + 14) * scale), radius=3 * scale, fill=color)
            text(painter, (x + 33, y - 7), name, 20)
            x += 135

    # The vertical section is the exact X=0 midline intersection, viewed from +X.
    side = data["side_section"]
    side_points = [p for loops in side for loop in loops for p in loop]
    side_depth = max(p[0] for p in side_points) - min(p[0] for p in side_points)
    side_height = max(p[1] for p in side_points) - min(p[1] for p in side_points)
    im, painter = new_canvas(1500, 1120)
    text(painter, (64, 40), "PROJECT PULSAR", 19, muted)
    text(painter, (64, 79), "头壳垂直剖面", 40)
    text(painter, (64, 140), "A—A  /  X = 0 mm  /  正中矢状切面", 23, muted)
    legend(painter, (1100, 111))
    vertical_transform = lambda p: (500 + p[0] * 2.5, 602 - p[1] * 2.5)
    for mm in range(-120, 141, 20):
        line(painter, [vertical_transform((mm, -140)), vertical_transform((mm, 160))])
    for mm in range(-140, 161, 20):
        line(painter, [vertical_transform((-140, mm)), vertical_transform((140, mm))])
    material(im, side, vertical_transform)
    text(painter, (500, 580), "内部空腔", 24, muted, anchor="mm")
    text(painter, (500, 617), "网格间距 20 mm", 18, muted, anchor="mm")
    text(painter, (155, 973), "后脑  -Y", 20, muted)
    text(painter, (850, 973), "面部  +Y", 20, muted, anchor="ra")
    line(painter, [(980, 230), (980, 973)])
    text(painter, (1040, 233), "切面位置 · 俯视", 26)
    plan_transform = lambda p: (1210 + p[0] * 1.25, 521 - p[1] * 1.25)
    material(im, data["sections"][1]["outlines"], plan_transform)
    line(painter, [(1210, 355), (1210, 690)], "#C74959", 3)
    text(painter, (1224, 356), "A", 22, "#C74959")
    text(painter, (1224, 664), "A", 22, "#C74959")
    text(painter, (1210, 329), "面部朝上", 18, muted, anchor="mm")
    text(painter, (1210, 741), "沿头部正中线前后切开", 19, muted, anchor="mm")
    text(painter, (1040, 827), f"截面外高  {side_height:.1f} mm", 24)
    text(painter, (1040, 877), f"截面外深  {side_depth:.1f} mm", 24)
    text(painter, (1040, 931), "尺寸仅指正中切面的外包络", 17, muted)
    line(painter, [(64, 1010), (1436, 1010)])
    text(painter, (64, 1033), "来源：ProjectPulsar_Base.blend · 实际求值网格与正中垂直面的交线", 19, muted)
    text(painter, (64, 1070), "蓝色为前壳，橙色为后壳；仅显示此平面切到的壳体材料，不含独立五金、内衬或佩戴者。", 18, muted)
    im.save(args.output / "head-vertical-section.png")

    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="1120" height="1280" viewBox="-140 -180 280 320">',
           '<rect x="-140" y="-180" width="280" height="320" fill="white"/>',
           '<g transform="scale(1,-1)">']
    for loops, color in zip(side, COLORS):
        path = " ".join("M " + " L ".join(f"{y:.5f},{z:.5f}" for y, z in loop) + " Z" for loop in loops)
        svg.append(f'<path d="{path}" fill="{color}" fill-rule="evenodd"/>')
    svg.append('</g></svg>')
    (args.output / "head-section-sagittal-x0mm.svg").write_text("\n".join(svg) + "\n")

    main = data["sections"][1]
    im, painter = new_canvas(1500, 1120)
    text(painter, (64, 40), "PROJECT PULSAR", 19, muted)
    text(painter, (64, 79), "头壳水平横切面", 40)
    text(painter, (64, 140), "A—A  /  Z = 0 mm  /  从头顶向下看", 23, muted)
    legend(painter, (1100, 111))
    section_plot(im, painter, main, (500, 575), 2.55)
    text(painter, (500, 560), "内部空腔", 24, muted, anchor="mm")
    text(painter, (500, 596), "网格间距 20 mm", 18, muted, anchor="mm")
    line(painter, [(980, 230), (980, 973)])
    text(painter, (1040, 233), "切面位置", 26)
    side_transform = lambda p: (1200 + p[0] * 1.35, 524 - p[1] * 1.35)
    material(im, data["side_section"], side_transform)
    line(painter, [(1020, 524), (1410, 524)], "#C74959", 3)
    text(painter, (1020, 505), "A", 22, "#C74959", anchor="lb")
    text(painter, (1410, 505), "A", 22, "#C74959", anchor="rb")
    text(painter, (1215, 773), "中线侧剖面 · 面部朝右", 17, muted, anchor="mm")
    text(painter, (1040, 835), f"截面外宽  {main['outer_span_mm'][0]:.1f} mm", 24)
    text(painter, (1040, 885), f"截面外深  {main['outer_span_mm'][1]:.1f} mm", 24)
    text(painter, (1040, 934), "尺寸仅指此高度的外包络", 17, muted)
    line(painter, [(64, 1010), (1436, 1010)])
    text(painter, (64, 1033), "来源：ProjectPulsar_Base.blend · 实际求值网格与水平面的交线", 19, muted)
    text(painter, (64, 1070), "Z 使用模型原始坐标；仅展示壳体，不含独立五金、内衬或佩戴者。", 18, muted)
    im.save(args.output / "head-horizontal-section.png")

    im, painter = new_canvas(1800, 960)
    text(painter, (60, 36), "PROJECT PULSAR  /  水平截面对照", 34)
    text(painter, (60, 96), "相同缩放比例 · 从头顶向下看 · 面部朝上 · 网格间距 20 mm", 22, muted)
    legend(painter, (1470, 70))
    for index, section in enumerate(data["sections"]):
        cx = 300 + index * 600
        text(painter, (cx, 179), f"Z = {section['z_mm']:+.0f} mm", 29, anchor="mm")
        section_plot(im, painter, section, (cx, 510), 1.7)
        width, depth = section["outer_span_mm"]
        text(painter, (cx, 832), f"外宽 {width:.1f} × 外深 {depth:.1f} mm", 21, anchor="mm")
    line(painter, [(60, 885), (1740, 885)])
    text(painter, (60, 910), "色块是切到的实体材料；通风孔、眼孔和接缝在部分高度会形成分开的截面轮廓。", 19, muted)
    im.save(args.output / "head-horizontal-sections-comparison.png")

    # Exact vector geometry with a millimetre viewBox, suitable for close inspection.
    for section in data["sections"]:
        svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="1120" height="1120" viewBox="-140 -140 280 280">',
               '<rect x="-140" y="-140" width="280" height="280" fill="white"/>',
               '<g transform="scale(1,-1)">']
        for loops, color in zip(section["outlines"], COLORS):
            path = " ".join("M " + " L ".join(f"{x:.5f},{y:.5f}" for x, y in loop) + " Z" for loop in loops)
            svg.append(f'<path d="{path}" fill="{color}" fill-rule="evenodd"/>')
        svg.append('</g></svg>')
        (args.output / f"head-section-z{section['z_mm']:+.0f}mm.svg").write_text("\n".join(svg) + "\n")
    print("PASS: 3 PNG illustrations and 4 exact contour SVGs written", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--draw", type=Path)
    parser.add_argument("--font", type=Path, default=Path("/System/Library/Fonts/Hiragino Sans GB.ttc"))
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else None)
    draw(args) if args.draw else extract(args)


if __name__ == "__main__":
    main()
