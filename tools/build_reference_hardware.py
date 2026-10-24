"""Build the reference-derived rounded rear with original mating interfaces.

Run on the pinned Front3mm baseline. No headform is loaded. The source rear
provides the rounded contour and triangular vent boundaries. The original rear
provides the flush seam, hinge and 20 x 20 latch seats. The result is a separate
editable blend; passing saved-file mechanical/mesh receipts are required for STL.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path
import bpy
import bmesh
import numpy as np
from mathutils import Vector
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_front_thickness import mesh_digest
from reference_interface_geometry import load_aligned, vent_annuli, warp, seam, width
from hinge_common import arrays, mesh_object, tube, AXIS, HARDWARE_NAMES
from repair_side_latches import box, solid_boolean
from validate_model import set_input, evaluated_metrics, failures
from validate_top_hinge import tree
SOURCE_SHA = '3dd5067826cda886d7c03bbe10719db12acdf16de927f5adbf7b1bd4783fff39'
BASELINE_SHA = '38125f437e2dd618255b23e39404d36fac5c1b9f3f79a5cd548a440ea3b38c32'

def build_surface(reference, registration):
    rv, rf = load_aligned(reference, registration)
    empty = mesh_object('Interface without old vents', [], [])
    set_input('后壳配置', '后壳打洞', empty)
    bpy.context.view_layer.update()
    ov, of = arrays('后壳配置')
    points = np.vstack((rv[warp(rv)[:, 1] < -25], ov[warp(ov)[:, 1] >= -25]))
    bm = bmesh.new()
    for p in points:
        bm.verts.new(p / 1000)
    bmesh.ops.convex_hull(bm, input=list(bm.verts), use_existing_faces=False)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context='VERTS')
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    me = bpy.data.meshes.new('Reference contour convex envelope')
    bm.to_mesh(me)
    bm.free()
    hull = bpy.data.objects.new('Reference contour convex envelope', me)
    bpy.context.scene.collection.objects.link(hull)
    ht = tree(*arrays(hull))
    center = np.array([0, -45, 30.0])
    bpy.ops.mesh.primitive_uv_sphere_add(segments=128, ring_count=64, radius=1, location=(0, 0, 0), rotation=(0, 0, 0))
    outer = bpy.context.object
    outer.name = 'Clean rounded outer skin'
    target_normal = []
    for vert in outer.data.vertices:
        direction = np.array(vert.co)
        direction /= np.linalg.norm(direction)
        hit, n, _, _ = ht.ray_cast(Vector(center + direction * 600), Vector(-direction), 1200)
        if hit is None:
            raise ValueError('Convex envelope ray missed')
        vert.co = Vector(np.array(hit) / 1000)
        target_normal.append(n[:])
    outer.data.update()
    bm = bmesh.new()
    bm.from_mesh(outer.data)
    bm.faces.ensure_lookup_table()
    removed = []
    for face in bm.faces:
        p = np.mean([v.co[:] for v in face.verts], axis=0) * 1000
        d = p - center
        d /= np.linalg.norm(d)
        _, normal, _, _ = ht.ray_cast(Vector(center + d * 600), Vector(-d), 1200)
        if p[2] < -60 and normal.z < -0.75:
            removed.append(face)
    bmesh.ops.delete(bm, geom=removed, context='FACES')
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context='VERTS')
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(outer.data)
    bm.free()
    outer.data.update()
    print('NECK CAP FACES', len(removed), flush=True)
    smooth = outer.modifiers.new('Smooth contour', 'SMOOTH')
    smooth.factor = 1.0
    smooth.iterations = 3
    sub = outer.modifiers.new('Even rounded skin', 'SUBSURF')
    sub.levels = 1
    sub.render_levels = 1
    # Blend the new outer skin onto the old contour before adding thickness.
    # A broad transition avoids a raised ridge at the body/collar junction.
    bpy.context.view_layer.update()
    skin = bpy.data.meshes.new_from_object(outer.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    matched = bpy.data.objects.new('Rounded quad skin matched to original seam', skin)
    bpy.context.scene.collection.objects.link(matched)
    # Use the original continuous head skin as the transition guide. The
    # mechanical rear includes holes and recesses that must not dent the skin.
    old_tree = tree(*arrays('头壳'))
    skin_points = np.array([p.co[:] for p in skin.vertices]) * 1000
    q = warp(skin_points)[:, 1]
    weight = np.clip((q + 40) / 18, 0, 1)
    weight = weight * weight * (3 - 2 * weight)
    weight *= np.clip((-q - 4) / 8, 0, 1)
    for index in np.flatnonzero(weight > 0):
        point = skin_points[index]
        direction = point - center
        radius = np.linalg.norm(direction)
        direction /= radius
        hit = old_tree.ray_cast(Vector(center + direction * 500), Vector(-direction), 600)[0]
        if hit is not None:
            target = np.dot(np.array(hit) - center, direction) + .03
            # A ray through the open front can hit the opposite wall. That is
            # not a corresponding skin point and must never drive the surface.
            if target > 0 and abs(target - radius) < 15:
                skin.vertices[index].co = Vector((point + weight[index] * (target - radius) * direction) / 1000)
    skin.update()
    outer = matched
    solid = outer.modifiers.new('Rear wall 3.2 mm', 'SOLIDIFY')
    solid.thickness = 0.0032
    solid.offset = -1
    solid.use_even_offset = True
    solid.use_quality_normals = True
    bpy.context.view_layer.update()
    sv, sf = arrays(outer)
    print('STOCK', len(sv), len(sf), flush=True)

    def crop(q, back):
        zs = np.r_[-400, np.arange(-110, 181, 0.5), 400]
        vertices = []
        faces = []
        for z in zs:
            split = float(seam(z) + q / 20 * width(z))
            lo, hi = (-400, split) if back else (split, 400)
            vertices.extend([(-400, lo, z), (400, lo, z), (400, hi, z), (-400, hi, z)])
        faces = [(3, 2, 1, 0), tuple(range(len(vertices) - 4, len(vertices)))]
        for k in range(len(zs) - 1):
            for i in range(4):
                j = (i + 1) % 4
                faces.append((4 * k + i, 4 * k + j, 4 * k + 4 + j, 4 * k + 4 + i))
        return mesh_object('Curved interface trim', vertices, faces)
    stock = mesh_object('Clean shell wall stock', sv, sf)
    old = mesh_object('Original collar stock', ov, of)
    back = solid_boolean([stock, crop(-14.5, True)], 'INTERSECT')
    collar = solid_boolean([old, crop(-16, False)], 'INTERSECT')
    joined = solid_boolean([back, collar], 'UNION')
    joined.name = 'Rounded rear with original interface'
    print('JOIN', evaluated_metrics(joined.name), flush=True)
    regions, _ = vent_annuli(rv, rf)
    source_tree = tree(rv, rf)
    cutters = []
    count = 0
    for region in regions:
        if warp(rv[np.unique(rf[region['faces']])])[:, 1].max() > -26:
            continue
        # Two annuli near the crown are blind hardware recesses, not vents.
        probe_center = region['center']
        probe_normal = probe_center - [0, -5, 10]
        probe_normal /= np.linalg.norm(probe_normal)
        if source_tree.ray_cast(Vector(probe_center - 10 * probe_normal), Vector(probe_normal), 20)[0] is not None:
            continue
        loops = region['loops']
        loop = max(loops, key=lambda loop: np.linalg.norm(rv[loop].mean(0) - [0, -5, 10]))
        boundary = rv[loop]
        origin = boundary.mean(0)
        normal = origin - [0, -5, 10]
        normal /= np.linalg.norm(normal)
        base = boundary - np.outer((boundary - origin) @ normal, normal)
        tangent = np.cross(normal, [0, 0, 1])
        tangent /= np.linalg.norm(tangent)
        second = np.cross(normal, tangent)
        xy = np.column_stack(((base - origin) @ tangent, (base - origin) @ second))
        order = sorted(range(len(xy)), key=lambda i: tuple(xy[i]))
        lower = []
        upper = []

        def cross(a, b, c):
            d = xy[b] - xy[a]
            e = xy[c] - xy[a]
            return d[0] * e[1] - d[1] * e[0]
        for i in order:
            while len(lower) > 1 and cross(lower[-2], lower[-1], i) <= 1e-09:
                lower.pop()
            lower.append(i)
        for i in reversed(order):
            while len(upper) > 1 and cross(upper[-2], upper[-1], i) <= 1e-09:
                upper.pop()
            upper.append(i)
        base = base[lower[:-1] + upper[:-1]]
        n = len(base)
        vertices = np.vstack((base - 20 * normal, base + 20 * normal))
        faces = [tuple(reversed(range(n))), tuple(range(n, 2 * n))]
        faces += [(i, (i + 1) % n, (i + 1) % n + n, i + n) for i in range(n)]
        cutter = mesh_object('Reference triangular vent', vertices, faces)
        bm = bmesh.new()
        bm.from_mesh(cutter.data)
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(cutter.data)
        bm.free()
        cutter.data.update()
        cutters.append(cutter)
        count += 1
    print('REFERENCE VENTS', count, flush=True)
    cutters.append(tube('Original D6.6 hinge bore', AXIS[0] - 100, AXIS[0] + 100, 3.3, center=AXIS[1:]))
    spec = json.loads(bpy.context.scene['pulsar_side_latch_specification'])
    for mount in spec['mounts']:
        if mount['index'] not in (0, 1):
            continue
        n = np.array(mount['inward_normal'])
        u = np.cross(n, [0, 0, 1])
        u /= np.linalg.norm(u)
        w = np.cross(n, u)
        basis = np.column_stack((n, u, w))
        center_hole = np.array(mount['seat_center_world_mm'])
        ob = tube('Original M3 rear bore', -3, 12, 1.75)
        for point in ob.data.vertices:
            point.co = Vector((np.array(point.co) * 1000 @ basis.T + center_hole) / 1000)
        bm = bmesh.new()
        bm.from_mesh(ob.data)
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(ob.data)
        bm.free()
        ob.data.update()
        cutters.append(ob)
    result = solid_boolean([joined, *cutters], 'DIFFERENCE')
    g = bpy.data.node_groups.new('Print cleanup', 'GeometryNodeTree')
    g.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    g.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    i = g.nodes.new('NodeGroupInput')
    o = g.nodes.new('NodeGroupOutput')
    m = g.nodes.new('GeometryNodeMergeByDistance')
    m.inputs['Mode'].default_value = 'All'
    m.inputs['Distance'].default_value = 1e-07
    c = g.nodes.new('GeometryNodeGroup')
    c.node_tree = bpy.data.node_groups['Pulsar 输出拓扑清理']
    g.links.new(i.outputs[0], m.inputs['Geometry'])
    g.links.new(m.outputs[0], c.inputs[0])
    g.links.new(c.outputs[0], o.inputs[0])
    result.modifiers.new('Print cleanup', 'NODES').node_group = g
    bpy.context.view_layer.update()
    result = mesh_object('Clean printable rear', *arrays(result))
    print('FINAL', evaluated_metrics(result.name), flush=True)
    return (result, outer, hull, empty, count)

def finish_surface(source):
    cutter = box('Neck finish Z -84 mm', [-400, -400, -400], [400, 400, -84])
    mod = source.modifiers.new('Exact neck and intersection finish', 'BOOLEAN')
    mod.operation, mod.solver, mod.use_self, mod.object = ('DIFFERENCE', 'EXACT', True, cutter)
    v, f = arrays(source)
    source.modifiers.clear()
    if len(f) < 50000:
        raise ValueError('Unexpected empty/small rear after exact Boolean')
    me = bpy.data.meshes.new('Millimetre finishing work')
    me.from_pydata(v.tolist(), [], f.tolist())
    me.update()
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=0.001)
    bmesh.ops.dissolve_degenerate(bm, dist=0.001, edges=list(bm.edges))
    bm.verts.index_update()
    groups = {}
    for face in bm.faces:
        groups.setdefault(tuple(sorted((v.index for v in face.verts))), []).append(face)
    remove = []
    for group in groups.values():
        if len(group) > 1:
            remove.extend(group if group[0].normal.dot(group[1].normal) < 0 else group[1:])
    bmesh.ops.delete(bm, geom=remove, context='FACES_ONLY')
    bmesh.ops.holes_fill(bm, edges=[e for e in bm.edges if e.is_boundary], sides=4)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context='VERTS')
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bmesh.ops.triangulate(bm, faces=list(bm.faces))
    bmesh.ops.dissolve_degenerate(bm, dist=0.001, edges=list(bm.edges))
    bmesh.ops.triangulate(bm, faces=list(bm.faces))
    for point in bm.verts:
        point.co /= 1000
    bm.to_mesh(me)
    bm.free()
    me.update()
    ob = bpy.data.objects.new('Finished rear', me)
    bpy.context.scene.collection.objects.link(ob)
    for step in range(5):
        v, f = arrays(ob)
        v, inverse = np.unique(v.astype(np.float32), axis=0, return_inverse=True)
        f = inverse[f]
        _, inverse, count = np.unique(np.sort(f, axis=1), axis=0, return_inverse=True, return_counts=True)
        f = f[count[inverse] == 1]
        for _ in range(10):
            e = np.sort(np.stack((f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]), axis=1), axis=2)
            _, inverse, count = np.unique(e.reshape(-1, 2), axis=0, return_inverse=True, return_counts=True)
            n = count[inverse].reshape(-1, 3)
            flap = np.any(n == 1, axis=1) & np.any(n > 2, axis=1)
            if not flap.any():
                break
            if np.any(np.linalg.norm(np.cross(v[f[flap, 1]] - v[f[flap, 0]], v[f[flap, 2]] - v[f[flap, 0]]), axis=1) > 0.02):
                raise ValueError('Refuse to remove a non-microscopic hanging face')
            f = f[~flap]
        used, inverse = np.unique(f, return_inverse=True)
        ob = mesh_object('Closed rear finish', v[used], inverse.reshape(-1, 3))
        if not failures(evaluated_metrics(ob.name)):
            break
    ob = repair_collinear_triangles(ob)
    if failures(evaluated_metrics(ob.name)):
        raise ValueError(('Rear finishing did not produce valid topology', evaluated_metrics(ob.name)))
    left = tube('D12.4 shoulder washer access', AXIS[0] - 100.2, AXIS[0] - 25.8, 6.2, center=AXIS[1:])
    right = tube('D12.4 M5 driver access', AXIS[0] + 28.2, AXIS[0] + 50.2, 6.2, center=AXIS[1:])
    result = solid_boolean([ob, left, right], 'DIFFERENCE')
    result = repair_collinear_triangles(result)
    metrics = evaluated_metrics(result.name)
    if len(result.data.polygons) < 50000 or failures(metrics):
        raise ValueError(('Rear access finish failed', metrics))
    return result


def repair_collinear_triangles(source):
    """Flip the long diagonal of near-collinear Boolean triangles in mm space.

    This retains every boundary vertex and changes only the triangulation of
    an adjacent four-vertex patch. It does not remesh mechanical surfaces.
    """
    v, f = arrays(source)
    me = bpy.data.meshes.new('Local triangulation repair mm')
    me.from_pydata(v.tolist(), [], f.tolist())
    me.update()
    bm = bmesh.new()
    bm.from_mesh(me)
    repaired = 0
    boundary = [edge for edge in bm.edges if edge.is_boundary]
    if boundary:
        if len(boundary) > 16:
            raise ValueError('Unexpected open rear boundary')
        print('LOCAL BOOLEAN CRACK', len(boundary), 'edges',
              [[tuple(v.co) for v in e.verts] for e in boundary], flush=True)
        filled = bmesh.ops.holes_fill(bm, edges=boundary, sides=8)['faces']
        if sum(face.calc_area() for face in filled) > .01:
            raise ValueError('Refuse to fill a substantial opening')
        bmesh.ops.triangulate(bm, faces=filled)
    for _ in range(8):
        bad = [face for face in bm.faces if face.calc_area() < 1e-9]
        if not bad:
            break
        for face in bad:
            if not face.is_valid:
                continue
            edge = max(face.edges, key=lambda e: e.calc_length())
            if len(edge.link_faces) != 2:
                raise ValueError('Cannot repair non-manifold skinny face')
            other = next(f for f in edge.link_faces if f != face)
            if len(other.verts) != 3:
                raise ValueError('Expected triangular neighbour')
            a, c = edge.verts
            b = next(v for v in face.verts if v not in edge.verts)
            d = next(v for v in other.verts if v not in edge.verts)
            bm.faces.remove(face)
            bm.faces.remove(other)
            bm.edges.remove(edge)
            bm.faces.new((a, b, d))
            bm.faces.new((b, c, d))
            repaired += 1
    if any(face.calc_area() < 1e-10 for face in bm.faces):
        raise ValueError('Collinear triangle repair did not converge')
    unseen = set(bm.verts)
    components = []
    while unseen:
        root = unseen.pop()
        stack, component = [root], [root]
        while stack:
            current = stack.pop()
            for edge in current.link_edges:
                other = edge.other_vert(current)
                if other in unseen:
                    unseen.remove(other)
                    stack.append(other)
                    component.append(other)
        components.append(component)
    components.sort(key=len, reverse=True)
    for component in components[1:]:
        if len(component) >= 100:
            raise ValueError('Unexpected disconnected rear component')
        faces = {face for point in component for face in point.link_faces}
        volume = abs(sum(face.verts[0].co.dot(face.verts[1].co.cross(face.verts[2].co)) / 6 for face in faces))
        if volume > 1:
            raise ValueError('Refuse to discard a substantial detached part')
        print('REMOVED BOOLEAN FRAGMENT', len(component), 'vertices', volume, 'mm3', flush=True)
        bmesh.ops.delete(bm, geom=component, context='VERTS')
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    for point in bm.verts:
        point.co = Vector(v[point.index] / 1000)
    bm.to_mesh(me)
    bm.free()
    me.update()
    ob = bpy.data.objects.new('Rear triangulation finish', me)
    bpy.context.scene.collection.objects.link(ob)
    print('COLLINEAR PATCHES', repaired, flush=True)
    return ob

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--registration', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    baseline = Path(bpy.data.filepath)
    if hashlib.sha256(baseline.read_bytes()).hexdigest() != BASELINE_SHA:
        raise ValueError('Load the pinned Front3mm baseline')
    if hashlib.sha256(args.reference.read_bytes()).hexdigest() != SOURCE_SHA:
        raise ValueError('Supplied rear source does not match archived source')
    if args.output.exists() or args.output.resolve() == baseline.resolve():
        raise ValueError('Use a new output path; never overwrite a source')
    original_objects = set(bpy.data.objects)
    names = ['前壳配置', *HARDWARE_NAMES, *[o.name for o in bpy.data.objects if 'pulsar_attached_shell' in o]]
    before = {name: mesh_digest(arrays(name)) for name in names}
    result, outer, hull, empty, vent_count = build_surface(args.reference, args.registration)
    result = finish_surface(result)
    legacy = bpy.data.objects['后壳配置']
    legacy.name = '历史后壳_原版分缝及锁座来源'
    result.name = '后壳配置'
    result['pulsar_print_role'] = 'reference_rear_hardware'
    result['nominal_body_wall_mm'] = 3.2
    result['source_policy'] = 'Reference-derived rounded skin; original seam and mechanical interfaces; no headform'
    construction = bpy.data.collections.new('圆润后壳_可编辑曲面与原始基准_不打印')
    bpy.context.scene.collection.children.link(construction)
    raw = mesh_object('用户后壳_原始刚体定位基准', *load_aligned(args.reference, args.registration))
    keep = {result, outer, hull, empty, raw}
    for item in set(bpy.data.objects) - original_objects - keep:
        bpy.data.objects.remove(item, do_unlink=True)
    for item in (outer, hull, empty, raw, legacy):
        for collection in list(item.users_collection):
            collection.objects.unlink(item)
        construction.objects.link(item)
        item.hide_render = True
        item.hide_set(True)
    construction.hide_viewport = True
    construction.hide_render = True
    result.color = (0.86, 0.58, 0.28, 1)
    material = bpy.data.materials.new('Rounded rear inspection gold')
    material.diffuse_color = result.color
    result.data.materials.append(material)
    scene = bpy.context.scene
    scene.name = 'ReferenceRearRounded_原版分缝与锁座'
    scene['pulsar_reference_hardware_revision'] = 1
    scene['pulsar_reference_hardware_source_sha256'] = SOURCE_SHA
    scene['pulsar_reference_hardware_policy'] = 'Smooth rounded reference contour, original flush seam and seats, obsolete lower tabs removed; no headform'
    for item in bpy.context.selected_objects:
        item.select_set(False)
    result.hide_set(False)
    result.hide_render = False
    result.select_set(True)
    bpy.context.view_layer.objects.active = result
    bpy.ops.object.shade_smooth_by_angle(angle=0.6)
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                area.spaces.active.shading.color_type = 'OBJECT'
                area.spaces.active.shading.show_shadows = False
    outer_name = outer.name
    args.output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output.resolve()), compress=True)
    bpy.ops.wm.open_mainfile(filepath=str(args.output.resolve()), load_ui=False)
    after = {name: mesh_digest(arrays(name)) for name in names}
    if after != before:
        raise ValueError('Front or original hardware changed')
    pose = json.loads(args.registration.read_text())['registration_for_comparison_only']
    report = {'blender': bpy.app.version_string, 'baseline': str(baseline), 'baseline_sha256': BASELINE_SHA, 'source': str(args.reference), 'source_sha256': SOURCE_SHA, 'blend': str(args.output), 'blend_sha256': hashlib.sha256(args.output.read_bytes()).hexdigest(), 'rigid_pose': {key: pose[key] for key in ('rotation_matrix', 'translation_mm')}, 'unchanged_mesh_digests': after, 'front_and_hardware_unchanged': True, 'rear_mesh_digest': mesh_digest(arrays('后壳配置')), 'rear_metrics': evaluated_metrics('后壳配置'), 'construction': {'method': 'Convex reference envelope sampled on a regular quad skin; smooth 3 iterations; subdivision 1; smooth radial match to original collar; inward Solidify 3.2 mm; original interface CSG', 'outer_skin_object': outer_name, 'vent_count': vent_count, 'neck_finish_z_mm': -84, 'new_body_cut_q': -14.5, 'original_collar_cut_q': -16, 'curve_crop_z_step_mm': 0.5, 'cleanup_distance_mm': 0.001}, 'headform_testing_performed': False, 'passed': True, 'acceptance': 'Build receipt only. Separate matching quality, hinge, latch and STL receipts required.'}
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print('PASS BUILD', report['rear_metrics'], flush=True)
if __name__ == '__main__':
    main()
