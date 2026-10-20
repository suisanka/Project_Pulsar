"""Validate evaluated meshes and millimetre STL topology inside Blender.

Run with --background --factory-startup --disable-autoexec --python-exit-code 1,
then the blend path and --python tools/validate_model.py -- --output receipt.json.
The loaded project is never saved.
"""

import argparse
import fnmatch
import hashlib
import itertools
import json
import sys
import time
from pathlib import Path

import bpy
import numpy as np


SHELLS = ("前壳配置", "后壳配置")
DEFAULTS = (
    ("前壳配置", "是否布尔", True),
    ("后壳配置", "是否布尔", True),
    ("前壳配置", "锁类型", 1),
    ("前壳配置", "前后基准值", 0.78),
    ("后壳配置", "圆角位置", 0.037),
    ("视孔", "生成", False),
    ("视孔", "反向", False),
    ("视孔", "瞳距", 6.03),
    ("眼线配置", "是否布尔", False),
    ("眼线配置", "是否刻字", False),
)


def set_input(object_name, input_name, value):
    obj = bpy.data.objects[object_name]
    for modifier in obj.modifiers:
        if modifier.type != "NODES":
            continue
        for socket in modifier.node_group.interface.items_tree:
            if (
                socket.item_type == "SOCKET"
                and socket.in_out == "INPUT"
                and socket.name == input_name
            ):
                if hasattr(modifier, "properties"):
                    target = getattr(modifier.properties.inputs, socket.identifier)
                    current = target.value
                    if current == value or (
                        isinstance(value, float) and abs(current - value) < 1e-7
                    ):
                        return
                    target.value = value
                else:
                    if modifier[socket.identifier] == value:
                        return
                    modifier[socket.identifier] = value
                obj.update_tag()
                return
    raise KeyError((object_name, input_name))


def get_input(object_name, input_name):
    for modifier in bpy.data.objects[object_name].modifiers:
        if modifier.type == "NODES":
            for socket in modifier.node_group.interface.items_tree:
                if (
                    socket.item_type == "SOCKET"
                    and socket.in_out == "INPUT"
                    and socket.name == input_name
                ):
                    if hasattr(modifier, "properties"):
                        return getattr(modifier.properties.inputs, socket.identifier).value
                    return modifier[socket.identifier]
    raise KeyError((object_name, input_name))


def triangle_metrics(vertices_mm, triangles):
    """Match vertices by actual float32 STL coordinates, not Blender indices."""
    vertices_mm = np.asarray(vertices_mm, dtype=np.float32)
    triangles = np.asarray(triangles, dtype=np.int32)
    if len(triangles) == 0:
        return {"vertices": len(vertices_mm), "triangles": 0}
    unique, remap = np.unique(vertices_mm, axis=0, return_inverse=True)
    faces = remap[triangles]
    directed = np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]))
    edges = np.sort(directed, axis=1).astype(np.uint64)
    keys = (edges[:, 0] << np.uint64(32)) | edges[:, 1]
    _, inverse, counts = np.unique(keys, return_inverse=True, return_counts=True)
    directions = np.where(directed[:, 0] < directed[:, 1], 1, -1)
    winding = np.bincount(inverse, weights=directions)
    points = vertices_mm[triangles].astype(np.float64)
    cross = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
    areas = np.linalg.norm(cross, axis=1) * 0.5
    sorted_faces = np.sort(faces, axis=1)
    order = np.lexsort((sorted_faces[:, 2], sorted_faces[:, 1], sorted_faces[:, 0]))
    sorted_faces = sorted_faces[order]
    duplicates = np.all(sorted_faces[1:] == sorted_faces[:-1], axis=1)
    return {
        "vertices": len(unique),
        "triangles": len(triangles),
        "boundary_edges": int(np.count_nonzero(counts == 1)),
        "multi_face_edges": int(np.count_nonzero(counts > 2)),
        "inconsistent_edges": int(np.count_nonzero((counts == 2) & (winding != 0))),
        "duplicate_triangles": int(np.count_nonzero(duplicates)),
        "degenerate_triangles": int(np.count_nonzero(areas <= 1e-12)),
        "near_zero_triangles": int(np.count_nonzero(areas < 1e-8)),
        "min_triangle_area_mm2": float(np.min(areas)),
        "dimensions_mm": (np.max(unique, axis=0) - np.min(unique, axis=0)).tolist(),
        "signed_volume_cm3": float(np.sum(points[:, 0] * cross) / 6000),
    }


def evaluated_metrics(name):
    obj = bpy.data.objects[name]
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        mesh.transform(obj.matrix_world)
        mesh.calc_loop_triangles()
        vertices = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", vertices)
        triangles = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int32)
        mesh.loop_triangles.foreach_get("vertices", triangles)
        result = triangle_metrics(vertices.reshape(-1, 3) * 1000, triangles.reshape(-1, 3))
        edge_faces = np.zeros(len(mesh.edges), dtype=np.int32)
        loop_edges = np.empty(len(mesh.loops), dtype=np.int32)
        mesh.loops.foreach_get("edge_index", loop_edges)
        np.add.at(edge_faces, loop_edges, 1)
        result["wire_edges"] = int(np.count_nonzero(edge_faces == 0))
        used = np.unique(triangles)
        result["loose_vertices"] = len(mesh.vertices) - len(used)
        marker = mesh.attributes.get("pulsar_output_rebuilt")
        result["sdf_rebuilt"] = bool(marker and any(value.value for value in marker.data))
        return result
    finally:
        evaluated.to_mesh_clear()


def read_stl(path):
    data = Path(path).read_bytes()
    count = int.from_bytes(data[80:84], "little")
    if len(data) != 84 + 50 * count:
        raise ValueError(f"Unexpected binary STL length: {path}")
    dtype = np.dtype(
        [("normal", "<f4", 3), ("vertices", "<f4", (3, 3)), ("attribute", "<u2")]
    )
    records = np.frombuffer(data, dtype=dtype, count=count, offset=84)
    return triangle_metrics(
        records["vertices"].reshape(-1, 3), np.arange(count * 3).reshape(-1, 3)
    )


def export_stl(name, path):
    # Export a frozen evaluated object in an isolated scene. This also exercises
    # Blender's actual exporter independently of the coordinate-based check.
    source_scene = bpy.context.window.scene
    obj = bpy.data.objects[name]
    depsgraph = bpy.context.evaluated_depsgraph_get()
    mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph), depsgraph=depsgraph)
    scene = bpy.data.scenes.new("Pulsar validation export")
    copy = bpy.data.objects.new("Validation export", mesh)
    scene.collection.objects.link(copy)
    copy.matrix_world = obj.matrix_world
    try:
        bpy.context.window.scene = scene
        copy.select_set(True)
        bpy.context.view_layer.objects.active = copy
        bpy.ops.wm.stl_export(
            filepath=str(path),
            export_selected_objects=True,
            global_scale=1000,
            apply_modifiers=True,
        )
        return read_stl(path)
    finally:
        bpy.context.window.scene = source_scene
        bpy.data.objects.remove(copy, do_unlink=True)
        bpy.data.meshes.remove(mesh)
        bpy.data.scenes.remove(scene)


def failures(metrics):
    errors = []
    if metrics.get("triangles", 0) == 0:
        return ["empty mesh"]
    for key in (
        "boundary_edges",
        "multi_face_edges",
        "inconsistent_edges",
        "duplicate_triangles",
        "degenerate_triangles",
        "wire_edges",
        "loose_vertices",
    ):
        if metrics.get(key, 0):
            errors.append(f"{key}={metrics[key]}")
    if metrics["signed_volume_cm3"] <= 0:
        errors.append("non-positive material volume")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--matrix", action="store_true", help="Test all 45 shell combinations")
    mode.add_argument("--current", action="store_true", help="Validate saved inputs without resets")
    parser.add_argument("--exports", type=Path, help="Also export/recheck representative STLs")
    parser.add_argument("--case", action="append", help="Run only matching case names (glob)")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
    receipt = {
        "blender": bpy.app.version_string,
        "blend_sha256": hashlib.sha256(Path(bpy.data.filepath).read_bytes()).hexdigest(),
        "degenerate_area_threshold_mm2": 1e-12,
        "near_zero_area_reporting_threshold_mm2": 1e-8,
        "cases": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.exports:
        args.exports.mkdir(parents=True, exist_ok=True)
    cases = [
        ("default", [], SHELLS),
        ("round_0.1", [("后壳配置", "圆角位置", 0.1)], SHELLS),
    ]
    if args.matrix:
        for lock, seam, rounding in itertools.product(
            (0, 1, 2), (0.0, 0.3, 0.65, 0.78, 0.85), (0.0, 0.037, 0.1)
        ):
            cases.append(
                (
                    f"lock{lock}_seam{seam}_round{rounding}",
                    [
                        ("前壳配置", "锁类型", lock),
                        ("前壳配置", "前后基准值", seam),
                        ("后壳配置", "圆角位置", rounding),
                    ],
                    SHELLS,
                )
            )
    for reverse, pupil in itertools.product((False, True), (5.5, 6.03, 7.0)):
        cases.append(
            (
                f"vision_reverse{reverse}_pupil{pupil}",
                [("视孔", "生成", True), ("视孔", "反向", reverse), ("视孔", "瞳距", pupil)],
                ("视孔", "前壳配置"),
            )
        )
    cases.extend(
        [
            ("eyeliner_boolean", [("眼线配置", "是否布尔", True)], ("眼线配置",)),
            (
                "eyeliner_engraving",
                [("眼线配置", "是否布尔", True), ("眼线配置", "是否刻字", True)],
                ("眼线配置",),
            ),
        ]
    )
    if args.current:
        for name in SHELLS:
            if not get_input(name, "是否布尔"):
                raise ValueError(f"{name}: enable 是否布尔 before validating print output")
        names = list(SHELLS)
        if get_input("视孔", "生成"):
            names.append("视孔")
        if get_input("眼线配置", "是否布尔") or get_input("眼线配置", "是否刻字"):
            names.append("眼线配置")
        cases = [("current", [], names)]
    if args.case:
        cases = [
            case for case in cases
            if any(fnmatch.fnmatchcase(case[0], pattern) for pattern in args.case)
        ]
        if not cases:
            raise ValueError("No cases matched --case")
    for label, changes, names in cases:
        start = time.perf_counter()
        desired = {} if args.current else {
            (obj, socket): value for obj, socket, value in (*DEFAULTS, *changes)
        }
        for (obj, socket), value in desired.items():
            set_input(obj, socket, value)
        bpy.context.view_layer.update()
        case = {"name": label, "inputs": changes, "meshes": {}, "errors": []}
        if args.current:
            case["inputs"] = [
                (obj, socket, get_input(obj, socket)) for obj, socket, _ in DEFAULTS
            ]
        for name in names:
            metrics = evaluated_metrics(name)
            case["meshes"][name] = metrics
            case["errors"].extend(f"{name}: {error}" for error in failures(metrics))
            if args.exports and label in ("current", "default", "round_0.1"):
                export = export_stl(name, args.exports / f"{label}_{name}.stl")
                case.setdefault("exports", {})[name] = export
                case["errors"].extend(f"STL {name}: {error}" for error in failures(export))
        case["seconds"] = round(time.perf_counter() - start, 3)
        receipt["cases"].append(case)
        receipt["passed"] = all(not item["errors"] for item in receipt["cases"])
        args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
        print(f"{'FAIL' if case['errors'] else 'PASS'} {label}: {case['errors']}", flush=True)
    if not args.current:
        for change in DEFAULTS:
            set_input(*change)
    if not receipt["passed"]:
        raise RuntimeError(f"Model validation failed; see {args.output}")
    print(f"PASS: {len(cases)} cases; project not saved", flush=True)


if __name__ == "__main__":
    main()
