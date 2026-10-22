"""Save a front-only wall-thickness variant without overwriting the source.

Run in Blender with the source blend loaded. Only the front shell's head-mesh
geometry inputs are replaced; seam anchors, ears, hardware and rear source
stay connected to their original inputs. Thickness is the nominal Solidify value,
before the existing subdivision and Boolean pipeline.
"""

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hinge_common import arrays
from validate_model import evaluated_metrics, failures, get_input


def mesh_digest(mesh):
    points, faces = mesh
    # Canonical STL-coordinate triangles tolerate harmless index reordering.
    vertices, inverse = np.unique(points[faces].astype(np.float32).reshape(-1, 3),
                                  axis=0, return_inverse=True)
    triangles = np.sort(inverse.reshape(-1, 3), axis=1)
    triangles = triangles[np.lexsort(triangles.T[::-1])]
    return hashlib.sha256(vertices.tobytes() + triangles.astype(np.int32).tobytes()).hexdigest()


def wall_samples(mesh, reference):
    points, faces = mesh
    tree = BVHTree.FromPolygons(points.tolist(), faces.tolist(), all_triangles=True)
    result = []
    for sample in reference['wall_samples']:
        if sample['shell'] != '前壳配置':
            continue
        outer, normal, _, distance = tree.find_nearest(Vector(sample['outer_xyz_mm']))
        direction = -normal
        epsilon = .0001
        inner, inner_normal, _, travel = tree.ray_cast(outer + direction * epsilon, direction, 20)
        if inner is None or direction.dot(inner_normal) <= 0:
            raise ValueError(f"Invalid wall ray: {sample['label']}")
        back, _, _, _ = tree.ray_cast(inner - direction * epsilon, -direction, 20)
        if back is None or (back - outer).length > .002:
            raise ValueError(f"Wall reverse-ray mismatch: {sample['label']}")
        result.append({'label': sample['label'], 'thickness_mm': travel + epsilon,
                       'previous_thickness_mm': sample['thickness_mm'],
                       'outer_xyz_mm': list(outer), 'inner_xyz_mm': list(inner),
                       'distance_from_reference_mm': distance,
                       'reverse_ray_error_mm': (back - outer).length})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--wall-reference', type=Path, required=True)
    parser.add_argument('--thickness-mm', type=float, default=3.0)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    source = Path(bpy.data.filepath).resolve()
    if args.output.resolve() == source or args.output.exists():
        raise ValueError('Output must be a new blend file, separate from the source')
    if not math.isfinite(args.thickness_mm) or not 0 < args.thickness_mm <= 10:
        raise ValueError('Thickness must be finite and in (0, 10] mm')
    if bpy.context.scene.get('pulsar_front_thickness_mm'):
        raise ValueError('A front thickness variant is already installed')
    reference = json.loads(args.wall_reference.read_text())
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if reference['source_sha256'] != digest:
        raise ValueError('Wall reference must describe this exact source blend')
    head = get_input('前壳配置', '头壳')
    solidify = next(m for m in head.modifiers if m.type == 'SOLIDIFY')
    if not all(abs(s - 1) < 1e-6 for s in head.scale) or solidify.offset != -1:
        raise ValueError('Expected a unit-scale head with inward Solidify')
    before = {name: mesh_digest(arrays(name)) for name in ('前壳配置', '后壳配置')}
    variant = head.copy()
    variant.name = f'头壳_前脸{args.thickness_mm:g}mm'
    bpy.context.scene.collection.objects.link(variant)
    next(m for m in variant.modifiers if m.type == 'SOLIDIFY').thickness = args.thickness_mm / 1000
    variant.hide_render = True
    variant.hide_set(True)
    variant['pulsar_role'] = 'front-only thickness source; nominal Solidify millimetres'
    # The public head input also drives the seam/hinge anchor. Preserve that
    # reference and replace only the preview and nested lock geometry sources.
    front = bpy.data.objects['前壳配置']
    modifier = next(m for m in front.modifiers if m.type == 'NODES')
    modifier.node_group = modifier.node_group.copy()
    group = modifier.node_group
    group.name = f'前壳配置_{args.thickness_mm:g}mm'
    replaced = []
    for node in group.nodes:
        socket = None
        if node.type == 'OBJECT_INFO':
            socket = node.inputs['Object']
        elif node.type == 'GROUP' and node.node_tree.name == '锁':
            socket = node.inputs['头壳']
        if socket is not None and socket.is_linked:
            link = socket.links[0]
            if link.from_node.type == 'GROUP_INPUT' and link.from_socket.name == '头壳':
                group.links.remove(link)
                socket.default_value = variant
                replaced.append(node.name)
    if len(replaced) != 2:
        raise ValueError(f'Expected preview and printable head geometry sources: {replaced}')
    front.update_tag()
    bpy.context.scene['pulsar_front_thickness_mm'] = args.thickness_mm
    bpy.context.scene['pulsar_front_thickness_source'] = variant.name
    bpy.context.view_layer.update()
    current = {name: arrays(name) for name in before}
    metrics = {name: evaluated_metrics(name) for name in before}
    for name, value in metrics.items():
        if failures(value):
            raise ValueError((name, failures(value)))
    if mesh_digest(current['后壳配置']) != before['后壳配置']:
        raise ValueError('Rear shell changed unexpectedly')
    if mesh_digest(current['前壳配置']) == before['前壳配置']:
        raise ValueError('Front shell did not change')
    report = {'source': str(source), 'source_sha256': digest,
              'blender': bpy.app.version_string,
              'nominal_front_thickness_mm': args.thickness_mm,
              'previous_nominal_thickness_mm': solidify.thickness * 1000,
              'source_object': variant.name, 'solidify_offset': -1,
              'replaced_geometry_nodes': replaced,
              'seam_anchor_source': head.name,
              'rear_geometry_unchanged': True, 'metrics': metrics,
              'wall_samples': wall_samples(current['前壳配置'], reference),
              'limits': ['Nominal Solidify setting precedes subdivision and Booleans; it is not a global minimum wall thickness.',
                         'Ears retain their original separate 2 mm source; mechanical pads and hinge retain their own dimensions.',
                         'This variant captures the current face controls; later face-control edits require keeping both head-source modifiers in sync.']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    if bpy.ops.wm.save_as_mainfile(filepath=str(args.output.resolve())) != {'FINISHED'}:
        raise RuntimeError('Failed to save variant')
    report['blend_sha256'] = hashlib.sha256(args.output.read_bytes()).hexdigest()
    report['passed'] = True
    args.receipt.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print('PASS: front thickness saved; rear geometry unchanged', flush=True)


if __name__ == '__main__':
    main()
