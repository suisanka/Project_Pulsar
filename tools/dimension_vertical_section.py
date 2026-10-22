"""Measure the saved midline section and annotate it without modifying the model.

In Blender: --sections <section.json> --output <measurements.json>
With Pillow: --draw <measurements.json> --sections <section.json> --output <folder>

Clearances are bounded line segments in the X=0 section. Wall thickness is the
first inward 3D surface-normal ray hit, not apparent horizontal cut thickness.
"""

import argparse
import hashlib
import html
import json
import math
import sys
from pathlib import Path


SHELLS = ("前壳配置", "后壳配置")
COLORS = ("#317DA1", "#D69546")


def line_hits(loops, axis, value):
    """Half-open edge rule avoids counting a shared vertex twice."""
    hits = []
    for loop in loops:
        for a, b in zip(loop, loop[1:] + loop[:1]):
            if (a[axis] <= value < b[axis]) or (b[axis] <= value < a[axis]):
                fraction = (value - a[axis]) / (b[axis] - a[axis])
                p = [a[i] + fraction * (b[i] - a[i]) for i in range(2)]
                hits.append(p)
    return sorted(hits, key=lambda p: p[1 - axis])


def interior(loops, point):
    return sum(p[0] > point[0] for p in line_hits(loops, 1, point[1])) % 2 == 1


def clear_span(side, axis, value, seed):
    """Find the first material boundary either side of a known empty point."""
    point = [seed, seed]
    point[axis] = value
    if any(interior(loops, point) for loops in side):
        raise ValueError(f"Clearance seed is inside material: {point}")
    hits = sorted((p for loops in side for p in line_hits(loops, axis, value)),
                  key=lambda p: p[1 - axis])
    below = [p for p in hits if p[1 - axis] < seed]
    above = [p for p in hits if p[1 - axis] > seed]
    if not below or not above:
        raise ValueError(f"Unbounded clearance on axis {axis}, coordinate {value}")
    a, b = below[-1], above[0]
    return {"start_yz_mm": a, "end_yz_mm": b,
            "length_mm": b[1 - axis] - a[1 - axis]}


def measure(args, section):
    import bpy
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from hinge_common import arrays
    from validate_model import failures, triangle_metrics

    source = Path(bpy.data.filepath)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != section["source_sha256"]:
        raise ValueError("Section data does not match the loaded .blend; regenerate it first")
    side = section["side_section"]
    result = {"source": source.name, "source_sha256": digest,
              "section_sha256": hashlib.sha256(args.sections.read_bytes()).hexdigest(),
              "blender": bpy.app.version_string, "units": "mm", "plane": "X=0",
              "clearances": [], "wall_samples": [], "source_checks": {},
              "definitions": {
                  "clearance": "First shell material on either side of a point in the cavity, measured along the specified Y or Z line in the X=0 plane.",
                  "wall": "First hit along the inward normal of the evaluated outer surface triangle. Samples are local, not a global minimum or constant wall thickness.",
                  "height": "H1 is at Y=80 mm, from chin interior to the underside of the top connection boss. The neck is open; no universal enclosed cavity height exists.",
                  "limitations": "Nominal digital geometry only; separate hardware, padding and print tolerances are not subtracted. Two-decimal wall labels are not manufacturing tolerances.",
              }}
    for label, height in (("D1", 80), ("D2", 0), ("D3", -60)):
        result["clearances"].append({"id": label, "axis": "Y", "z_mm": height,
                                     **clear_span(side, 1, height, 0)})
    result["clearances"].append({"id": "H1", "axis": "Z", "y_mm": 80,
                                 **clear_span(side, 0, 80, 0)})
    # Each selection refers to an outer-shell point, not an arbitrary pixel.
    samples = [
        ("T1", "顶部", 1, 0, 0, -1),
        ("T2", "上后脑", 1, 1, 80, 0),
        ("T3", "下后脑", 1, 1, 0, 0),
        ("T4", "额头", 0, 1, 80, -1),
        ("T5", "眉鼻间", 0, 1, 0, -1),
        ("T6", "鼻尖", 0, None, None, None),
        ("T7", "口部", 0, 1, -90, -1),
        ("T8", "下巴底部", 0, 0, 80, 0),
    ]
    trees = []
    for name in SHELLS:
        vertices, faces = arrays(name)
        metrics = triangle_metrics(vertices, faces)
        errors = failures(metrics)
        if errors:
            raise ValueError(f"{name}: {errors}")
        result["source_checks"][name] = metrics
        trees.append(BVHTree.FromPolygons(vertices, faces, all_triangles=True))
    # Independently verify the 2D contour dimensions against first hits on the
    # original 3D shell meshes, including any intervening connection geometry.
    for item in result["clearances"]:
        seed = Vector((0, 0, item["z_mm"])) if item["axis"] == "Y" else Vector((0, item["y_mm"], 0))
        direction = Vector((0, 1, 0)) if item["axis"] == "Y" else Vector((0, 0, 1))
        errors = []
        for sign, key in ((-1, "start_yz_mm"), (1, "end_yz_mm")):
            hits = [tree.ray_cast(seed, direction * sign, 400) for tree in trees]
            hit = min((h for h in hits if h[0] is not None), key=lambda h: h[3])
            error = (hit[0] - Vector((0, *item[key]))).length
            if error > 0.001:
                raise ValueError(f"{item['id']}: contour/3D ray mismatch {error} mm")
            errors.append(error)
        item["mesh_ray_endpoint_errors_mm"] = errors
    epsilon = 0.0001
    for code, label, shell, axis, value, which in samples:
        if axis is None:
            yz = max((p for loop in side[shell] for p in loop), key=lambda p: p[0])
        else:
            yz = line_hits(side[shell], axis, value)[which]
        requested = Vector((0, *yz))
        tree = trees[shell]
        outer, normal, face, distance = tree.find_nearest(requested)
        if distance > 0.001:
            raise ValueError(f"{code}: section to mesh mismatch {distance} mm")
        direction = -normal
        inner, inner_normal, inner_face, travel = tree.ray_cast(outer + direction * epsilon, direction, 30)
        if inner is None:
            raise ValueError(f"{code}: no inner wall within 30 mm")
        thickness = travel + epsilon
        if direction.dot(inner_normal) <= 0:
            raise ValueError(f"{code}: ray did not exit the same wall; length={thickness}, normal_dot={direction.dot(inner_normal)}")
        # Reversing the chord must return to the same outer surface.
        back, _, _, _ = tree.ray_cast(inner - direction * epsilon, -direction, 30)
        if back is None or (back - outer).length > 0.002:
            raise ValueError(f"{code}: reverse-ray check failed")
        if not 0.5 < thickness < 10:
            raise ValueError(f"{code}: unexpected shell thickness {thickness}")
        result["wall_samples"].append({"id": code, "label": label, "shell": SHELLS[shell],
            "thickness_mm": thickness, "outer_xyz_mm": list(outer), "inner_xyz_mm": list(inner),
            "inward_normal": list(direction), "outer_triangle": face, "inner_triangle": inner_face,
            "section_to_mesh_distance_mm": distance, "reverse_ray_error_mm": (back - outer).length,
            "x_departure_mm": abs(inner.x)})
    if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
        raise RuntimeError("Source changed during measurement")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"clearances": result["clearances"], "wall_samples": result["wall_samples"]}, ensure_ascii=False), flush=True)


def draw(args, section):
    from PIL import Image, ImageChops, ImageDraw, ImageFont

    measurements = json.loads(args.draw.read_text())
    if measurements["source_sha256"] != section["source_sha256"] or measurements["section_sha256"] != hashlib.sha256(args.sections.read_bytes()).hexdigest():
        raise ValueError("Measurements and section data do not match")
    width, height, scale = 2000, 1440, 2
    bg, ink, muted, green = "#F8FAFB", "#203746", "#647887", "#14836D"
    im = Image.new("RGB", (width * scale, height * scale), bg)
    painter = ImageDraw.Draw(im)
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
           f'<rect width="{width}" height="{height}" fill="{bg}"/>']

    def line(points, color=ink, weight=1):
        painter.line([(round(x * scale), round(y * scale)) for x, y in points], fill=color, width=weight * scale)
        svg.append(f'<polyline points="{" ".join(f"{x:.3f},{y:.3f}" for x,y in points)}" stroke="{color}" stroke-width="{weight}" fill="none"/>')

    def text(x, y, message, size=24, color=ink, center=False, box=False):
        font = ImageFont.truetype(str(args.font), size * scale)
        extent = painter.textbbox((0, 0), message, font=font)
        tw = (extent[2] - extent[0]) / scale
        if center:
            x -= tw / 2
        if box:
            painter.rectangle(((x - 8) * scale, (y - 3) * scale, (x + tw + 8) * scale, (y + size + 7) * scale), fill=bg)
            svg.append(f'<rect x="{x-8}" y="{y-3}" width="{tw+16}" height="{size+10}" fill="{bg}"/>')
        painter.text((x * scale, y * scale), message, fill=color, font=font, anchor="lt")
        svg.append(f'<text x="{x:.3f}" y="{y + size * 0.86:.3f}" font-size="{size}" fill="{color}" font-family="Hiragino Sans GB, Noto Sans CJK SC, sans-serif">{html.escape(message)}</text>')

    def dot(x, y, color, radius=4):
        painter.ellipse(((x-radius)*scale, (y-radius)*scale, (x+radius)*scale, (y+radius)*scale), fill=color)
        svg.append(f'<circle cx="{x}" cy="{y}" r="{radius}" fill="{color}"/>')

    def dimension(a, b):
        line([a, b], green, 2)
        length = math.dist(a, b)
        dx, dy = (b[0]-a[0])/length, (b[1]-a[1])/length
        for p, sign in ((a, 1), (b, -1)):
            line([(p[0]+sign*10*dx+4*dy, p[1]+sign*10*dy-4*dx), p,
                  (p[0]+sign*10*dx-4*dy, p[1]+sign*10*dy+4*dx)], green, 2)
            line([(p[0]-5*dy,p[1]+5*dx),(p[0]+5*dy,p[1]-5*dx)], green)

    transform = lambda p: (650 + p[0] * 3, 765 - p[1] * 3)
    text(66, 38, "PROJECT PULSAR / DIMENSIONED SECTION", 20, muted)
    text(66, 84, "正中垂直剖面 · 内部净空与局部壁厚", 42)
    text(66, 150, "X = 0 mm  /  面部朝右  /  单位：mm  /  网格间距：20 mm", 24, muted)
    for y in range(-120, 141, 20):
        line([transform((y,-140)), transform((y,160))], "#E5EBEE")
    for z in range(-140,161,20):
        line([transform((-140,z)),transform((140,z))], "#E5EBEE")
    for loops, color in zip(section["side_section"], COLORS):
        mask = Image.new("1", im.size, 0)
        paths = []
        for loop in loops:
            points = [transform(p) for p in loop]
            layer = Image.new("1", im.size, 0)
            ImageDraw.Draw(layer).polygon([(round(x*scale),round(y*scale)) for x,y in points],fill=1)
            mask=ImageChops.logical_xor(mask,layer)
            paths.append("M " + " L ".join(f"{x:.3f},{y:.3f}" for x,y in points) + " Z")
        im.paste(color,mask=mask)
        svg.append(f'<path d="{" ".join(paths)}" fill="{color}" fill-rule="evenodd"/>')
    for item in measurements["clearances"]:
        a,b=transform(item["start_yz_mm"]),transform(item["end_yz_mm"])
        dimension(a,b)
        if item["axis"]=="Y":
            text((a[0]+b[0])/2-65,a[1]-14,f"{item['id']}  {item['length_mm']:.1f}",24,green,center=True,box=True)
        else:
            text(a[0]-42,675,"H1",23,green,box=True)
    # Leader labels are separated from the clearance arrows and the geometry.
    placements = {
        "T1": (480, 225), "T2": (80, 452), "T3": (80, 734),
        "T4": (1090, 452), "T5": (1090, 734), "T6": (1090, 900),
        "T7": (1090, 1040), "T8": (825, 1240),
    }
    for item in measurements["wall_samples"]:
        point=transform(item["outer_xyz_mm"][1:])
        x,y=placements[item["id"]]
        color=COLORS[SHELLS.index(item["shell"])]
        end=(x+125,y+20) if x<200 else (x,y+20)
        line([point, (end[0],point[1]),end],color,1)
        dot(*point,color)
        text(x,y,f"{item['id']}  {item['thickness_mm']:.2f}",25,color,box=True)
    text(300,1235,"后脑",22,muted)
    text(1100,1235,"面部",22,muted)
    line([(1350,240),(1350,1280)],"#D5DFE5")
    text(1405,250,"内部净空",30,green)
    row=310
    for item in measurements["clearances"]:
        label=f"Z = {item['z_mm']:+.0f}" if "z_mm" in item else "Y = +80"
        text(1405,row,f"{item['id']}  {item['length_mm']:.1f} mm",27,green)
        text(1710,row+3,label,21,muted)
        row+=58
    text(1405,555,"D1–D3：指定高度处的前后净深",21,muted)
    text(1405,592,"H1：下巴内侧至顶部连接座下表面",21,muted)
    text(1405,650,"局部壁厚 · 沿外表面法线",28)
    for i,item in enumerate(measurements["wall_samples"]):
        y=710+i*47
        color=COLORS[SHELLS.index(item["shell"])]
        text(1405,y,f"{item['id']}  {item['label']}",24,color)
        text(1770,y,f"{item['thickness_mm']:.2f} mm",24,color)
    text(1405,1125,"蓝色：前壳    橙色：后壳",22,muted)
    text(1405,1165,"壁厚为选定点实测，不代表全壳最小值。",20,muted)
    text(1405,1204,"H1 仅在指定竖线上成立；颈部下方开放。",20,muted)
    line([(66,1310),(1935,1310)],"#D5DFE5")
    text(66,1338,"来源：ProjectPulsar_Base.blend 的实际求值网格；标注位置与测量端点均保存在 JSON 记录中。",22,muted)
    text(66,1380,"净空未扣除独立五金、内衬和打印偏差。壁厚显示至 0.01 mm 仅为数值读数精度，不是制造公差。",21,muted)
    args.output.mkdir(parents=True,exist_ok=True)
    im.save(args.output/"head-vertical-section-dimensioned.png")
    (args.output/"head-vertical-section-dimensioned.svg").write_text("\n".join([*svg,"</svg>"])+"\n")
    print("PASS: dimensioned PNG and vector SVG written",flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sections",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--draw",type=Path)
    parser.add_argument("--font",type=Path,default=Path("/System/Library/Fonts/Hiragino Sans GB.ttc"))
    args=parser.parse_args(sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else None)
    section=json.loads(args.sections.read_text())
    draw(args,section) if args.draw else measure(args,section)


if __name__=="__main__":
    main()
