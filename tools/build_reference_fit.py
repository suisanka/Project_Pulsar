"""Build a separate rear-clearance variant, preserving the Front3mm face.

Run in Blender with the Front3mm source loaded. Distances are millimetres in
reports and metres in Blender. Supplied STL files are evidence only: they are
not a wearer scan, assembly-coordinate source, or replacement mechanical part.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_front_thickness import mesh_digest
from hinge_common import HARDWARE_NAMES, SHELL_NAMES, arrays
from validate_model import evaluated_metrics, failures, read_stl, set_input


def smooth_weight(y_mm):
    t = np.clip((-45.0 - y_mm) / 65.0, 0.0, 1.0)
    return t**3 * (10.0 - 15.0*t + 6.0*t*t)


def install_local_cleanup(obj):
    """Remove the new Boolean sliver only within a 0.2 mm local selection.

    The connected-edge merge removes two vertices/four triangles at the saved
    default. It does not weld the shell globally or touch the hinge artifact.
    """
    group = bpy.data.node_groups.new('Pulsar Reference Fit Local Sliver Cleanup', 'GeometryNodeTree')
    group.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    group.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    nodes, links = group.nodes, group.links
    inp, out = nodes.new('NodeGroupInput'), nodes.new('NodeGroupOutput')
    pos = nodes.new('GeometryNodeInputPosition')
    distance = nodes.new('ShaderNodeVectorMath')
    distance.operation = 'DISTANCE'
    links.new(pos.outputs[0], distance.inputs[0])
    distance.inputs[1].default_value = obj.matrix_world.inverted() @ Vector((-.11753, -.00414, .04356))
    selected = nodes.new('ShaderNodeMath')
    selected.operation = 'LESS_THAN'
    links.new(distance.outputs['Value'], selected.inputs[0])
    selected.inputs[1].default_value = .0002
    merge = nodes.new('GeometryNodeMergeByDistance')
    merge.inputs['Mode'].default_value = 'Connected'
    merge.inputs['Distance'].default_value = .00004
    links.new(inp.outputs[0], merge.inputs['Geometry'])
    links.new(selected.outputs[0], merge.inputs['Selection'])
    links.new(merge.outputs[0], out.inputs[0])
    for i, node in enumerate(nodes):
        node.location = ((i % 4)*240, -(i//4)*210)
    obj.modifiers.new('局部布尔细边清理 / 0.2 mm 范围', 'NODES').node_group = group


def install_rear_expansion(obj, back_mm):
    """Monotone Y-only stretch; no displacement at Y >= -45 mm.

    Unlike a proximity-weighted warp this has no X/Z shear. In the continuous
    map dY'/dY >= 1. Mesh topology and sampled wall thickness are still checked
    independently, since the exported triangles approximate that map.
    """
    group = bpy.data.node_groups.new('Pulsar Reference Fit Rear Expansion', 'GeometryNodeTree')
    group.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    group.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    amount = group.interface.new_socket(name='后脑扩展 mm', in_out='INPUT', socket_type='NodeSocketFloat')
    amount.default_value = back_mm
    amount.min_value = 0
    amount.max_value = 60
    amount.description = 'Validated default 40 mm; any edit requires fit and assembly revalidation'
    nodes, links = group.nodes, group.links
    inp = nodes.new('NodeGroupInput')
    out = nodes.new('NodeGroupOutput')
    pos = nodes.new('GeometryNodeInputPosition')
    xyz = nodes.new('ShaderNodeSeparateXYZ')
    links.new(pos.outputs[0], xyz.inputs[0])
    world_y = nodes.new('ShaderNodeMath')
    world_y.operation = 'ADD'
    links.new(xyz.outputs['Y'], world_y.inputs[0])
    world_y.inputs[1].default_value = obj.matrix_world.translation.y
    ramp = nodes.new('ShaderNodeMapRange')
    ramp.interpolation_type = 'SMOOTHERSTEP'
    ramp.clamp = True
    links.new(world_y.outputs[0], ramp.inputs['Value'])
    ramp.inputs['From Min'].default_value = -.045
    ramp.inputs['From Max'].default_value = -.110
    ramp.inputs['To Min'].default_value = 0
    ramp.inputs['To Max'].default_value = 1
    mm = nodes.new('ShaderNodeMath')
    mm.operation = 'MULTIPLY'
    links.new(inp.outputs['后脑扩展 mm'], mm.inputs[0])
    mm.inputs[1].default_value = -.001
    displacement = nodes.new('ShaderNodeMath')
    displacement.operation = 'MULTIPLY'
    links.new(mm.outputs[0], displacement.inputs[0])
    links.new(ramp.outputs['Result'], displacement.inputs[1])
    vector = nodes.new('ShaderNodeCombineXYZ')
    links.new(displacement.outputs[0], vector.inputs['Y'])
    move = nodes.new('GeometryNodeSetPosition')
    links.new(inp.outputs['Geometry'], move.inputs['Geometry'])
    links.new(vector.outputs[0], move.inputs['Offset'])
    links.new(move.outputs[0], out.inputs['Geometry'])
    for i, node in enumerate(nodes):
        node.location = ((i % 4)*240, -(i//4)*210)
    modifier = obj.modifiers.new('后脑空间 / 参考壳结构修订', 'NODES')
    modifier.node_group = group


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--reference-front', type=Path, required=True)
    parser.add_argument('--reference-rear', type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    source = Path(bpy.data.filepath).resolve()
    if args.output.exists() or args.output.resolve() == source:
        raise ValueError('Output must be a new independent blend file')
    if bpy.context.scene.get('pulsar_front_thickness_mm') != 3.0:
        raise ValueError('Load the existing Front3mm variant')
    if bpy.context.scene.get('pulsar_reference_fit_revision'):
        raise ValueError('Reference fit is already installed')
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    references = []
    for path in (args.reference_front, args.reference_rear):
        metrics = read_stl(path)
        if failures(metrics):
            raise ValueError((str(path), failures(metrics)))
        references.append({'filename': path.name, 'source_path': str(path.resolve()),
                           'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                           'bytes': path.stat().st_size, 'metrics': metrics})
    before = {name: arrays(name) for name in SHELL_NAMES}
    hardware_names = [*HARDWARE_NAMES, *[o.name for o in bpy.data.objects if 'pulsar_attached_shell' in o]]
    hardware_before = {name: mesh_digest(arrays(name)) for name in hardware_names}
    set_input('后壳配置', '圆角位置', .055)
    bpy.context.view_layer.update()
    rear = bpy.data.objects[SHELL_NAMES[1]]
    if not np.allclose(np.array(rear.matrix_world)[:3, :3], np.eye(3), atol=1e-7):
        raise ValueError('Y deformation requires identity rotation/scale')
    unclean = arrays(rear)
    install_local_cleanup(rear)
    bpy.context.view_layer.update()
    relief = arrays(rear)
    install_rear_expansion(rear, 40.0)
    bpy.context.view_layer.update()
    after = {name: arrays(name) for name in SHELL_NAMES}
    expected = relief[0].copy()
    expected[:, 1] -= 40.0*smooth_weight(expected[:, 1])
    delta = float(np.linalg.norm(expected-after[SHELL_NAMES[1]][0], axis=1).max())
    if not np.array_equal(relief[1], after[SHELL_NAMES[1]][1]) or delta > .001:
        raise ValueError('Geometry Nodes does not match the analytical Y map')
    if mesh_digest(before[SHELL_NAMES[0]]) != mesh_digest(after[SHELL_NAMES[0]]):
        raise ValueError('Front shell changed')
    if any(mesh_digest(arrays(n)) != d for n, d in hardware_before.items()):
        raise ValueError('Hardware envelopes changed')
    metrics = {name: evaluated_metrics(name) for name in SHELL_NAMES}
    if any(failures(m) for m in metrics.values()):
        raise ValueError(metrics)
    scene = bpy.context.scene
    scene['pulsar_reference_fit_revision'] = 1
    scene['pulsar_reference_fit_status'] = 'Digital prototype; wearer scan, donning path and physical fit not validated'
    scene['pulsar_reference_fit_parameters'] = json.dumps({'back_mm': 40, 'fixed_y_ge_mm': -45,
                                                         'full_y_le_mm': -110, 'rear_round': .055,
                                                         'clearance_target_mm': 7})
    scene['pulsar_reference_fit_reference_hashes'] = json.dumps([r['sha256'] for r in references])
    for name, color in zip(SHELL_NAMES, ((.32, .64, .82, 1), (.86, .58, .28, 1))):
        obj = bpy.data.objects[name]
        obj.color = color
        obj.hide_set(False)
        obj.hide_render = False
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                area.spaces.active.shading.color_type = 'OBJECT'
                area.spaces.active.shading.show_shadows = False
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if bpy.ops.wm.save_as_mainfile(filepath=str(args.output.resolve()), compress=True) != {'FINISHED'}:
        raise RuntimeError('Save failed')
    if hashlib.sha256(source.read_bytes()).hexdigest() != source_hash:
        raise RuntimeError('Source was modified')
    report = {'source': str(source), 'source_sha256': source_hash,
              'output': str(args.output), 'blend_sha256': hashlib.sha256(args.output.read_bytes()).hexdigest(),
              'blender': bpy.app.version_string, 'references': references,
              'reference_units': 'STL is unitless; mm assumed from shell scale and project convention',
              'reference_alignment': 'Individually rotated/zeroed files; no verified common assembly transform',
              'design_transfer': 'Separate removable face/rear parts and rear cranial enclosure; no copied face or hardware geometry',
              'parameters': json.loads(scene['pulsar_reference_fit_parameters']),
              'front_unchanged': True, 'hardware_unchanged': True,
              'front_min_y_mm': float(before[SHELL_NAMES[0]][0][:, 1].min()),
              'hardware_min_y_mm': min(float(arrays(n)[0][:, 1].min()) for n in hardware_names),
              'rear_bounds_before_mm': [before[SHELL_NAMES[1]][0].min(0).tolist(), before[SHELL_NAMES[1]][0].max(0).tolist()],
              'rear_bounds_after_mm': [after[SHELL_NAMES[1]][0].min(0).tolist(), after[SHELL_NAMES[1]][0].max(0).tolist()],
              'geometry_nodes_analytical_max_error_mm': delta, 'metrics': metrics,
              'local_cleanup': {'center_world_mm': [-117.53, -4.14, 43.56],
                                'selection_radius_mm': .2, 'connected_merge_distance_mm': .04,
                                'vertices_removed': len(unclean[0])-len(relief[0]),
                                'triangles_removed': len(unclean[1])-len(relief[1])},
              'passed': True, 'limits': ['Build/topology pass only; independent fit, wall and mechanical checks required.',
                                        'Reference STL does not establish wearer dimensions or physical fit.']}
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print('PASS: reference-fit variant built', json.dumps(metrics, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
