"""Install the D6 x 55 / M5 shoulder-axle hinge; save only to --output.

Run in Blender with --disable-autoexec. The old r pin remains archived, unused.
Cutters follow the existing parametric hinge anchor; the hardware preview and
motion acceptance apply to the documented default head configuration only.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hinge_common import ANCHOR, AXIS, REVISION, SHELL_NAMES, SPEC, hardware, tube
from validate_model import DEFAULTS, evaluated_metrics, failures, get_input


def insert_cut(name, cutter, label):
    group = bpy.data.objects[name].modifiers[0].node_group
    base = group.nodes['部件并集']
    destinations = [link.to_socket for link in list(base.outputs[0].links)]
    frame = group.nodes.new('NodeFrame')
    frame.name = 'Pulsar_Hinge_' + label
    frame.label = '顶部铰链修复 / ' + label
    info = group.nodes.new('GeometryNodeObjectInfo')
    info.inputs['Object'].default_value = cutter
    instance = group.nodes.new('GeometryNodeInstanceOnPoints')
    realize = group.nodes.new('GeometryNodeRealizeInstances')
    boolean = group.nodes.new('GeometryNodeMeshBoolean')
    boolean.operation = 'DIFFERENCE'
    boolean.solver = 'MANIFOLD'
    for index, node in enumerate((info, instance, realize, boolean)):
        node.parent = frame
        node.name = 'Pulsar_Hinge_' + label + '_' + str(index)
        node.location = (index * 220, 0)
    # Use the existing anchor before export-coordinate compensation.
    group.links.new(group.nodes['设置位置'].outputs[0], instance.inputs['Points'])
    group.links.new(info.outputs['Geometry'], instance.inputs['Instance'])
    group.links.new(instance.outputs[0], realize.inputs[0])
    group.links.new(base.outputs[0], boolean.inputs[0])
    group.links.new(realize.outputs[0], boolean.inputs[1])
    for destination in destinations:
        group.links.new(boolean.outputs[0], destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    scene = bpy.context.scene
    if scene.get('pulsar_hinge_revision'):
        raise ValueError('Hinge revision already installed; do not add duplicate cutters')
    for obj, key, expected in DEFAULTS:
        actual = get_input(obj, key)
        if abs(float(actual) - float(expected)) > 1e-6:
            raise ValueError(f'Restore documented defaults before this build: {obj}/{key}')
    receipt = {'source_sha256': hashlib.sha256(Path(bpy.data.filepath).read_bytes()).hexdigest(), 'specification': SPEC}
    receipt['before'] = {name: evaluated_metrics(name) for name in SHELL_NAMES}
    helpers = bpy.data.collections.new('Pulsar_Hinge_Cutters')
    scene.collection.children.link(helpers)
    center = (AXIS[1]-ANCHOR[1], AXIS[2]-ANCHOR[2])
    bore = tube('Pulsar_Hinge_Bore_D6p6', -110, 110, 3.3, center=center, collection=helpers)
    gap = tube('Pulsar_Hinge_Front_Axial_Clearance', -14, 14, 8, center=center, collection=helpers)
    entry = tube('Pulsar_Hinge_Left_Insertion_Channel', -110, -25.8, 6.5, center=center, collection=helpers)
    for name in SHELL_NAMES:
        insert_cut(name, bore, '同轴孔_6p6')
        insert_cut(name, entry, '左侧插入通道')
    insert_cut(SHELL_NAMES[0], gap, '耳轴轴向间隙')
    for obj in helpers.objects:
        obj.hide_set(True)
        obj.hide_render = True
        obj['pulsar_print_role'] = 'boolean_helper'
    # These rigid tongues collide with the front shell during 0..4 degrees.
    # External side-latch seats and their original posts remain in the union.
    group = bpy.data.objects[SHELL_NAMES[1]].modifiers[0].node_group
    removed = []
    for link in list(group.nodes['部件并集'].inputs[1].links):
        if link.from_node.name in ('插扣并集', '插扣镜像_翻转'):
            removed.append(link.from_node.name)
            group.links.remove(link)
    if sorted(removed) != ['插扣并集', '插扣镜像_翻转']:
        raise ValueError('Unexpected rear tongue wiring')
    receipt['disconnected_rigid_tongue_nodes'] = removed
    # Manifold can create nearly coincident, separately indexed vertices at
    # large-rounding intersections. STL float32 collapses them even when the
    # native topology looks valid. Weld at 0.0001 mm before the existing cleanup
    # and lazy SDF checks so the topology inspected is also export-safe.
    triangle = group.nodes['输出三角化']
    targets = [link.to_socket for link in triangle.outputs[0].links]
    weld = group.nodes.new('GeometryNodeMergeByDistance')
    weld.name = 'Pulsar_Hinge_STL_近重合顶点'
    weld.label = 'STL 近重合顶点 / 0.0001 mm'
    weld.inputs['Mode'].default_value = 'All'
    weld.inputs['Distance'].default_value = 1e-7
    group.links.new(triangle.outputs[0], weld.inputs['Geometry'])
    for target in targets:
        group.links.new(weld.outputs[0], target)
    legacy = bpy.data.objects['r插销']
    legacy.hide_set(True)
    legacy.hide_render = True
    legacy['pulsar_print_role'] = 'legacy_unused'
    legacy['说明'] = '旧版未定位 R 形样件；修订 2 使用 D6x55/M5 金属肩轴，本件不装配、不导出。'
    collection = bpy.data.collections.new('Pulsar_Hinge_Hardware_Assembly')
    scene.collection.children.link(collection)
    hardware(collection)
    scene['pulsar_hinge_revision'] = REVISION
    scene['pulsar_hinge_specification'] = json.dumps(SPEC, ensure_ascii=False)
    bpy.context.view_layer.update()
    receipt['after'] = {name: evaluated_metrics(name) for name in SHELL_NAMES}
    errors = [f'{name}: {error}' for name, metrics in receipt['after'].items() for error in failures(metrics)]
    if errors:
        raise ValueError(errors)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output.resolve()))
    receipt['saved_sha256'] = hashlib.sha256(args.output.read_bytes()).hexdigest()
    receipt['geometry_passed'] = True
    receipt['assembly_validation'] = 'Run validate_top_hinge.py on the saved file separately.'
    args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n')
    print('PASS: hinge geometry saved; independent assembly validation still required', flush=True)


if __name__ == '__main__':
    main()
