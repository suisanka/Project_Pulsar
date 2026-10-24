"""Use the user's rear STL verbatim, with no headform fitting or deformation.

Native STL coordinates and triangle winding remain exact in a millimetre scene.
A separate scene positions a linked mesh by rotation/translation only, for
interface comparison with Front3mm. It is not an accepted mixed assembly.
"""

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hinge_common import AXIS, arrays
from validate_model import triangle_metrics, failures


def read_native(path):
    data = path.read_bytes()
    count = int.from_bytes(data[80:84], 'little')
    if len(data) != 84 + 50*count:
        raise ValueError('Expected binary STL')
    records = np.frombuffer(data, dtype=[('normal', '<f4', 3), ('vertices', '<f4', (3, 3)), ('attribute', '<u2')], offset=84)
    v, remap = np.unique(records['vertices'].reshape(-1, 3), axis=0, return_inverse=True)
    return data, v, remap.reshape(-1, 3), records['vertices']


def native_object(name, v, f, scene):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(v, [], f)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    scene.collection.objects.link(obj)
    for face in mesh.polygons:
        face.use_smooth = True
    return obj


def scene_mm(name):
    s = bpy.data.scenes.new(name)
    s.unit_settings.system = 'METRIC'
    s.unit_settings.scale_length = .001
    s.unit_settings.length_unit = 'MILLIMETERS'
    s.render.engine = 'BLENDER_WORKBENCH'
    s.render.resolution_x = 1000
    s.render.resolution_y = 1000
    s.render.resolution_percentage = 100
    s.render.image_settings.file_format = 'PNG'
    s.view_settings.view_transform = 'Standard'
    s.display.shading.light = 'STUDIO'
    s.display.shading.color_type = 'OBJECT'
    s.display.shading.show_shadows = False
    s.display.shading.show_cavity = True
    s.display.shading.cavity_type = 'BOTH'
    s.display.shading.background_type = 'WORLD'
    s.world = bpy.data.worlds.new(name+' background')
    s.world.color = (.91, .93, .95)
    return s


def hinge_frame(v, f):
    """Fit the source hinge bore using its long, parallel cylinder edges.

    The approximate direction only selects the observed lateral cylinder in
    this supplied STL; the final axis/centre/radius are measured from vertices.
    """
    p = v[f].astype(float)
    a = np.concatenate([p[:, i] for i in (0, 1, 2)])
    b = np.concatenate([p[:, i] for i in (1, 2, 0)])
    edges = b-a
    lengths = np.linalg.norm(edges, axis=1)
    estimate = np.array([math.sqrt(3)/2, -.5, 0])
    selected = (lengths > 25) & (lengths < 30) & (abs(edges@estimate/np.maximum(lengths, 1e-12)) > .99999)
    if selected.sum() < 48:
        raise ValueError('Source hinge feature could not be identified')
    e = edges[selected].copy()
    e[e@estimate < 0] *= -1
    axis = np.linalg.svd(e, full_matrices=False)[2][0]
    if axis@estimate < 0:
        axis *= -1
    u = np.cross([0, 0, 1], axis)
    u /= np.linalg.norm(u)
    z = np.cross(axis, u)
    midpoint = (a[selected]+b[selected])/2
    q = np.column_stack((midpoint@u, midpoint@z))
    solution = np.linalg.lstsq(np.column_stack((2*q, np.ones(len(q)))), (q*q).sum(1), rcond=None)[0]
    center_2d = solution[:2]
    radius = math.sqrt(solution[2]+center_2d@center_2d)
    center = axis*np.median(midpoint@axis)+u*center_2d[0]+z*center_2d[1]
    residual = float(abs(np.linalg.norm(q-center_2d, axis=1)-radius).max())
    if residual > .03 or not 1.8 < radius < 2.5:
        raise ValueError('Unexpected source hinge circle')
    return np.stack((-axis, -u, z)), center, {
        'axis_source': axis.tolist(), 'center_source_mm': center.tolist(),
        'bore_diameter_mm': 2*radius, 'circle_max_residual_mm': residual,
        'axis_edge_count': int(selected.sum()), 'axis_edge_length_range_mm': [float(lengths[selected].min()), float(lengths[selected].max())]}


def comparison_pose(v, f, baseline):
    frame, center, hinge = hinge_frame(v, f)
    target = BVHTree.FromPolygons(*baseline, all_triangles=True)
    sample = v[::max(1, len(v)//2500)].astype(float)
    trials = []
    best = None
    for degrees in np.arange(-10, 40.01, .5):
        angle = math.radians(degrees)
        rot = np.array([[1, 0, 0], [0, math.cos(angle), -math.sin(angle)], [0, math.sin(angle), math.cos(angle)]])@frame
        move = AXIS-rot@center
        distances = np.array([target.find_nearest(p)[3] for p in sample@rot.T+move])
        rms = float(np.sqrt(np.mean(np.sort(distances)[:int(.8*len(distances))]**2)))
        trials.append({'angle_deg': float(degrees), 'trimmed_rms_mm': rms})
        if best is None or rms < best[0]:
            best = (rms, float(degrees), rot, move)
    rms, degrees, rot, move = best
    return rot, move, {'source_hinge': hinge, 'target_axis_mm': AXIS.tolist(),
                       'rotation_matrix': rot.tolist(), 'translation_mm': move.tolist(),
                       'angle_about_lateral_axis_deg': degrees, 'trimmed_rms_to_old_rear_mm': rms,
                       'method': 'Align measured hinge axis/centre, then rotate only about that axis to compare outer shells; no scale or shape fitting',
                       'assembly_verified': False, 'trials': trials}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reference', type=Path, required=True)
    p.add_argument('--source-copy', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--export', type=Path, required=True)
    p.add_argument('--receipt', type=Path, required=True)
    p.add_argument('--images', type=Path, required=True)
    p.add_argument('--qa-scripts', type=Path, required=True)
    args = p.parse_args(sys.argv[sys.argv.index('--')+1:])
    baseline = Path(bpy.data.filepath).resolve()
    if args.output.exists() or args.output.resolve() == baseline:
        raise ValueError('Use a new independent output blend')
    baseline_hash = hashlib.sha256(baseline.read_bytes()).hexdigest()
    front = arrays('前壳配置')
    rear = arrays('后壳配置')
    bpy.context.scene.name = '历史Front3mm_前壳编辑源_旧后壳不用'
    bpy.data.objects['后壳配置'].name = '历史后壳_Front3mm_不作为当前方案'
    data, v, f, corners = read_native(args.reference)
    digest = hashlib.sha256(data).hexdigest()
    metrics = triangle_metrics(v, f)
    if failures(metrics):
        raise ValueError(failures(metrics))
    # Byte copies preserve STL normals, ordering and header as well as geometry.
    for path in (args.source_copy, args.export):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != data:
                raise ValueError(f'Refusing to overwrite different content: {path}')
        else:
            path.write_bytes(data)
        if path.read_bytes() != data:
            raise RuntimeError('Byte copy failed')
    raw_scene = scene_mm('后壳照抄_原始STL坐标')
    raw = native_object('后半头壳_用户原始数据_不变形', v, f, raw_scene)
    raw.color = (.86, .58, .28, 1)
    raw['source_sha256'] = digest
    raw['geometry_policy'] = 'Exact supplied STL coordinates and winding. No modifiers, scaling, cleanup, remesh, wall change or headform fit.'
    raw['pulsar_print_role'] = 'exact_user_rear'
    view_scene = scene_mm('接口对照_后壳原样_非装配验收')
    comparison = raw.copy()
    comparison.name = '后半头壳_仅旋转平移对照'
    view_scene.collection.objects.link(comparison)
    rot, move, registration = comparison_pose(v, f, rear)
    transform = np.eye(4)
    transform[:3, :3] = rot
    transform[:3, 3] = move
    comparison.matrix_world = Matrix(transform)
    comparison['placement_only'] = True
    old_front = native_object('前壳3mm_接口对照_未适配', *front, view_scene)
    old_front.color = (.40, .66, .81, 1)
    old_front['pulsar_print_role'] = 'comparison_only'
    world = v.astype(float)@rot.T+move
    overlaps = len(BVHTree.FromPolygons(world, f, all_triangles=True).overlap(BVHTree.FromPolygons(*front, all_triangles=True)))
    view_scene['pulsar_reference_rear_exact_revision'] = 1
    view_scene['assembly_status'] = 'Interface comparison only: original rear bore/seam/latches have not been converted to Closure v4.'
    bpy.context.window.scene = view_scene
    cam = bpy.data.objects.new('ReferenceRear_Review_Camera', bpy.data.cameras.new('ReferenceRear_Review_Camera'))
    view_scene.collection.objects.link(cam)
    view_scene.camera = cam
    cam.data.type = 'ORTHO'
    cam.data.clip_start = .01
    cam.data.clip_end = 100000
    args.images.mkdir(parents=True, exist_ok=True)
    center = Vector((world.min(0)+world.max(0))/2)
    def render(name, direction, with_front=False, wire=False):
        old_front.hide_render = not with_front
        cam.location = center+Vector(direction).normalized()*1000
        cam.rotation_euler = (center-cam.location).to_track_quat('-Z', 'Y').to_euler()
        cam.data.ortho_scale = 360
        view_scene.render.filepath = str(args.images/(name+'.png'))
        bpy.ops.render.render(write_still=True)
    render('rear-exact-outside', (1, -1, .25))
    render('rear-exact-inside', (0, 1, 0))
    render('rear-exact-interface-comparison', (1, .2, .1), with_front=True)
    wire = comparison.copy()
    wire.name = '临时线框审阅'
    wire.data = comparison.data.copy()
    view_scene.collection.objects.link(wire)
    wire.color = (.015, .02, .025, 1)
    wire_mod = wire.modifiers.new('Thin review wire only', 'WIREFRAME')
    wire_mod.thickness = .008
    wire_mod.use_even_offset = False
    wire_mod.offset = 1
    render('rear-exact-wire', (1, -1, .25))
    bpy.data.objects.remove(wire, do_unlink=True)
    # Save with the unchanged rear prominent, the front comparison hidden.
    old_front.hide_render = True
    old_front.hide_set(True)
    bpy.ops.object.select_all(action='DESELECT')
    comparison.select_set(True)
    bpy.context.view_layer.objects.active = comparison
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                space = area.spaces.active
                space.shading.color_type = 'OBJECT'
                space.shading.show_shadows = False
                space.clip_end = 100000
                space.region_3d.view_distance = 440
                space.region_3d.view_location = center
                space.region_3d.view_rotation = (center-cam.location).to_track_quat('-Z', 'Y')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    raw_name, raw_scene_name = raw.name, raw_scene.name
    if bpy.ops.wm.save_as_mainfile(filepath=str(args.output.resolve()), compress=True) != {'FINISHED'}:
        raise RuntimeError('Save failed')
    # Reopen the actual deliverable, then compare every native triangle corner.
    bpy.ops.wm.open_mainfile(filepath=str(args.output.resolve()), load_ui=False)
    saved = bpy.data.objects[raw_name]
    saved_v = np.empty(len(saved.data.vertices)*3, dtype=np.float32)
    saved.data.vertices.foreach_get('co', saved_v)
    saved_f = np.array([tuple(p.vertices) for p in saved.data.polygons])
    exact = np.array_equal(saved_v.reshape(-1, 3)[saved_f], corners)
    if not exact or len(saved.modifiers) or not np.allclose(saved.scale, 1):
        raise RuntimeError('Saved native mesh differs from the supplied triangles')
    bpy.context.window.scene = bpy.data.scenes[raw_scene_name]
    sys.path.insert(0, str(args.qa_scripts.resolve()))
    import qa_check
    qa = qa_check.run(objects=[saved.name], profile='print', uv=False, eps=1e-5, tol=.001)
    # Source fidelity takes precedence over repairing inherited source findings.
    report = {'source': str(args.reference), 'source_sha256': digest,
              'source_copy': str(args.source_copy), 'export': str(args.export),
              'source_copy_sha256': hashlib.sha256(args.source_copy.read_bytes()).hexdigest(),
              'export_sha256': hashlib.sha256(args.export.read_bytes()).hexdigest(),
              'blend': str(args.output), 'blend_sha256': hashlib.sha256(args.output.read_bytes()).hexdigest(),
              'baseline': str(baseline), 'baseline_sha256': baseline_hash,
              'blender': bpy.app.version_string, 'metrics': metrics,
              'native_stl_bounds_mm': [v.min(0).tolist(), v.max(0).tolist()],
              'saved_native_triangle_corners_exact': exact, 'stl_byte_identical': True,
              'headform_testing_performed': False, 'deformation_applied': False,
              'registration_for_comparison_only': registration,
              'front_rear_intersection_triangle_pairs_at_comparison_pose': overlaps,
              'raw_source_qa': qa,
              'passed': exact and args.export.read_bytes() == data,
              'acceptance': 'Exact rear-source adoption only. No claim of mixed assembly acceptance.',
              'limits': ['Source STL has no unit metadata; millimetres adopted from the supplied shell and project convention.',
                         'Original bore, wall, vents, tabs and seam are retained verbatim; Closure v4 hardware is not automatically compatible.',
                         'Comparison pose is a rigid geometric registration, not a validated assembly pose.',
                         'Original file is immutable: any QA findings are reported, never automatically repaired.']}
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    if hashlib.sha256(baseline.read_bytes()).hexdigest() != baseline_hash:
        raise RuntimeError('Baseline modified')
    print('PASS EXACT COPY', json.dumps({k: report[k] for k in ('source_sha256', 'metrics', 'saved_native_triangle_corners_exact', 'stl_byte_identical', 'front_rear_intersection_triangle_pairs_at_comparison_pose')}, ensure_ascii=False), flush=True)
    print('SOURCE HINGE', json.dumps(registration['source_hinge']), 'QA', qa['errors'], flush=True)


if __name__ == '__main__':
    main()
