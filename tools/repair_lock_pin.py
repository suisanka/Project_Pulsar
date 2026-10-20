"""Repair and export the independent r插销; run inside Blender with -- arguments."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_model import (
    SHELLS, evaluated_metrics, evaluated_positions_mm, export_stl, failures,
)


def shell_fingerprint(name):
    obj = bpy.data.objects[name]
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        mesh.transform(obj.matrix_world)
        mesh.calc_loop_triangles()
        positions = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
        triangles = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int32)
        mesh.vertices.foreach_get('co', positions)
        mesh.loop_triangles.foreach_get('vertices', triangles)
        return hashlib.sha256(positions.tobytes() + triangles.tobytes()).hexdigest()
    finally:
        evaluated.to_mesh_clear()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--stl', type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    obj = bpy.data.objects['r插销']
    if obj.data.users != 1 or obj.modifiers or obj.data.shape_keys:
        raise ValueError('Expected an independent, unmodified pin mesh')
    before_positions = np.unique(evaluated_positions_mm(obj.name), axis=0)
    receipt = {
        'blender': bpy.app.version_string,
        'source_sha256': hashlib.sha256(Path(bpy.data.filepath).read_bytes()).hexdigest(),
        'object': obj.name,
        'shells_before': {name: shell_fingerprint(name) for name in SHELLS},
        'before': evaluated_metrics(obj.name),
    }
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-8)
        bmesh.ops.dissolve_degenerate(bm, edges=list(bm.edges), dist=1e-9)
        bmesh.ops.triangulate(
            bm, faces=list(bm.faces), quad_method='BEAUTY', ngon_method='BEAUTY',
        )
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(obj.data)
    finally:
        bm.free()
    obj.data.update()
    bpy.context.view_layer.update()
    receipt['after'] = evaluated_metrics(obj.name)
    receipt['unique_vertex_positions_unchanged'] = np.array_equal(
        before_positions, np.unique(evaluated_positions_mm(obj.name), axis=0),
    )
    receipt['shells_after'] = {name: shell_fingerprint(name) for name in SHELLS}
    if failures(receipt['after']) or not receipt['unique_vertex_positions_unchanged']:
        raise ValueError('Pin cleanup failed geometry checks')
    if receipt['shells_before'] != receipt['shells_after']:
        raise ValueError('Pin cleanup changed a shell')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.stl.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt['stl_metrics'] = export_stl(obj.name, args.stl)
    if failures(receipt['stl_metrics']):
        raise ValueError('Exported pin failed topology checks')
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output.resolve()))
    receipt['saved_sha256'] = hashlib.sha256(args.output.read_bytes()).hexdigest()
    receipt['stl'] = str(args.stl)
    receipt['stl_sha256'] = hashlib.sha256(args.stl.read_bytes()).hexdigest()
    receipt['stl_bytes'] = args.stl.stat().st_size
    receipt['passed'] = True
    args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
    print('PASS: independent pin repaired and exported; shell geometry unchanged')


if __name__ == '__main__':
    main()
