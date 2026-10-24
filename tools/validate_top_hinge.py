"""Read-only saved-file checks for hinge assembly, access and motion.

The motion check is a full-mesh, discrete rigid-body scan (0.25 degrees).
It is not an FEA, fatigue test, slicer result or physical acceptance test.
"""

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hinge_common import AXIS, AXLE_NAME, CHECKED_ANGLE, HARDWARE_NAMES, REVISION, SHELL_NAMES, SPEC, arrays, rotated, tube
from validate_model import DEFAULTS, evaluated_metrics, failures, get_input


def tree(points, faces):
    return BVHTree.FromPolygons(points.tolist(), faces.tolist(), all_triangles=True)


def inside(bvh, point):
    votes = []
    for direction in ((.193, .337, .921), (.719, -.431, .547), (-.271, .883, -.367)):
        direction = Vector(direction).normalized()
        origin = Vector(point)
        hits = 0
        for _ in range(200):
            hit, _, _, _ = bvh.ray_cast(origin, direction)
            if hit is None:
                break
            hits += 1
            origin = hit + direction * .0001  # 0.1 micron, in millimetres
        else:
            raise RuntimeError('Parity ray did not escape a closed mesh')
        votes.append(hits % 2 == 1)
    return sum(votes) >= 2


def component_seeds(points, faces):
    """One surface point for every connected component, including cavity walls."""
    parent = np.arange(len(points))
    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for a, b, c in faces:
        ra, rb, rc = root(a), root(b), root(c)
        parent[rb] = ra
        parent[rc] = ra
    seeds = {}
    for i in range(len(points)):
        seeds.setdefault(int(root(i)), i)
    return points[list(seeds.values())]


def collision(a_tree, b_tree, a_seeds, b_seeds):
    pairs = len(a_tree.overlap(b_tree))
    # A surface intersection test alone misses complete containment.
    contained_b = sum(inside(a_tree, p) for p in b_seeds)
    contained_a = sum(inside(b_tree, p) for p in a_seeds)
    return {'surface_pairs': pairs, 'a_components_inside_b': contained_a, 'b_components_inside_a': contained_b}


def boolean_intersection_volume(a, b, degrees):
    """Independent solid intersection using Blender's Manifold boolean solver."""
    from hinge_common import mesh_object
    va, fa = a
    vb, fb = b
    one = mesh_object('Hinge_check_A', va, fa)
    two = mesh_object('Hinge_check_B', rotated(vb, degrees), fb)
    output = mesh_object('Hinge_check_intersection', [], [])
    group = bpy.data.node_groups.new('Hinge check intersection', 'GeometryNodeTree')
    group.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    modifier = output.modifiers.new('Intersection', 'NODES')
    modifier.node_group = group
    boolean = group.nodes.new('GeometryNodeMeshBoolean')
    boolean.operation = 'INTERSECT'
    boolean.solver = 'MANIFOLD'
    for obj in (one, two):
        info = group.nodes.new('GeometryNodeObjectInfo')
        info.inputs['Object'].default_value = obj
        group.links.new(info.outputs['Geometry'], boolean.inputs[1])
    end = group.nodes.new('NodeGroupOutput')
    group.links.new(boolean.outputs[0], end.inputs[0])
    bpy.context.view_layer.update()
    vertices, faces = arrays(output)
    if len(faces):
        p = vertices[faces]
        volume = abs(float(np.sum(p[:, 0] * np.cross(p[:, 1]-p[:, 0], p[:, 2]-p[:, 0])) / 6))
    else:
        volume = 0.0
    for obj in (one, two, output):
        mesh = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.meshes.remove(mesh)
    bpy.data.node_groups.remove(group)
    return {'angle_deg': degrees, 'triangles': len(faces), 'intersection_volume_mm3': volume}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--step', type=float, default=.25)
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    if not 0 < args.step <= .25:
        raise ValueError('Step must be in (0, 0.25] degrees')
    if bpy.context.scene.get('pulsar_hinge_revision') != REVISION:
        raise ValueError('Expected hinge revision 2')
    for obj, key, expected in DEFAULTS:
        if abs(float(get_input(obj, key))-float(expected)) > 1e-6:
            raise ValueError(f'Motion acceptance is for documented defaults: {obj}/{key}')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        'blender': bpy.app.version_string,
        'blend_sha256': hashlib.sha256(Path(bpy.data.filepath).read_bytes()).hexdigest(),
        'specification': SPEC, 'errors': [],
        'method': 'Full evaluated triangle meshes, BVH surface overlap plus connected-component parity containment; independent Manifold solid intersections at four angles.',
        'limits': ['Discrete rigid geometry only; not a continuous collision proof.', 'No purchased hardware measurement, slicing, print, elasticity, wear, fatigue or load test.'],
    }
    def require(condition, description):
        if not condition:
            report['errors'].append(description)
    side_parts = {obj.name: obj['pulsar_attached_shell'] for obj in bpy.data.objects if 'pulsar_attached_shell' in obj}
    data = {name: arrays(name) for name in (*SHELL_NAMES, *HARDWARE_NAMES, *side_parts)}
    trees = {name: tree(*value) for name, value in data.items()}
    seeds = {name: component_seeds(*value) for name, value in data.items()}
    report['mesh_checks'] = {name: evaluated_metrics(name) for name in data}
    for name, metrics in report['mesh_checks'].items():
        require(not failures(metrics), f'{name}: {failures(metrics)}')
    report['component_counts'] = {name: len(value) for name, value in seeds.items()}
    front, rear = SHELL_NAMES
    fixed_side = [name for name, shell in side_parts.items() if shell == front]
    moving_side = [name for name, shell in side_parts.items() if shell == rear]
    report['side_fastener_attachments'] = side_parts
    if side_parts:
        report['limits'].append('Side latch fasteners are included; the purchased latch moving covers/internal mechanism are not supplied as CAD and are not motion-validated.')
    report['hardware_closed'] = {}
    for name in HARDWARE_NAMES:
        report['hardware_closed'][name] = {}
        for shell in SHELL_NAMES:
            hit = collision(trees[shell], trees[name], seeds[shell], seeds[name])
            report['hardware_closed'][name][shell] = hit
            require(not any(hit.values()), f'{name} collides with {shell} at rest')
    # Swept cylinders represent the entire straight insertion travel, not just
    # two endpoints. Right-side small parts are staged inside the shell at X=45.
    access = [
        ('shaft_insertion', -100, 36.9, 3.0, 'closed'),
        ('head_and_left_washer_insertion', -100, -26.0, 6.0, 'closed'),
        ('right_spacer_and_washer_insertion', 26.0, 50.0, 5.0, 'closed'),
        ('right_nut_driver_OD12_body', 28.4, 50.0, 6.0, 'closed'),
        ('right_driver_extension_OD3', 33.4, 100, 1.5, 'closed'),
        ('left_hex_key_envelope', -100, -32.1, 1.8, 'closed'),
    ]
    report['assembly_access'] = []
    for label, x0, x1, radius, _ in access:
        obj = tube('Access check', x0, x1, radius)
        obj.location = Vector(AXIS/1000)
        bpy.context.view_layer.update()
        points, faces = arrays(obj)
        bvh = tree(points, faces)
        hits = {shell: collision(trees[shell], bvh, seeds[shell], points[:1]) for shell in SHELL_NAMES}
        report['assembly_access'].append({'name': label, 'swept_x_mm': [x0, x1], 'radius_mm': radius, 'shells': hits})
        require(not any(value for hit in hits.values() for value in hit.values()), label+' blocked')
        mesh = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.meshes.remove(mesh)
    # Measure clearance from the evaluated bore, independently of the cutter spec.
    report['bore_measurements'] = {}
    for name, intervals in ((front, [(-25.0,-14.2),(14.2,25.0)]), (rear, [(-13.0,13.0)])):
        radii = []
        for x0, x1 in intervals:
            for x in np.linspace(x0, x1, math.ceil((x1-x0)/.2)+1):
                origin = Vector(AXIS+np.array([x,0,0]))
                for angle in np.linspace(0, 2*math.pi, 64, endpoint=False):
                    direction = Vector((0,math.cos(angle),math.sin(angle)))
                    _, _, _, distance = trees[name].ray_cast(origin, direction, 20)
                    if distance is None:
                        report['errors'].append(name+' missing bearing wall')
                    else:
                        radii.append(distance)
        report['bore_measurements'][name] = {'rays': len(radii), 'min_radius_mm': min(radii), 'max_radius_mm': max(radii), 'min_radial_clearance_to_D6_mm': min(radii)-3}
        require(min(radii)>3.28, name+' bore clearance below 0.28 mm')
    def bearing_x(name):
        # New annular end faces have vertices only on their inner/outer rings;
        # measuring vertices in an intermediate radial band misses those faces.
        # Use axial-facing triangle centroids instead, independently of spec X.
        vertices, faces = data[name]
        triangles = vertices[faces]-AXIS
        p = triangles.mean(axis=1)
        normals = np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
        length = np.linalg.norm(normals,axis=1)
        axial = abs(normals[:,0]) > .9999*length
        r = np.linalg.norm(p[:,1:],axis=1)
        return p[axial&(length>1e-10)&(r>3.4)&(r<6.0)&(abs(p[:,0])<27),0]
    xf, xr = bearing_x(front), bearing_x(rear)
    measurements = {
        'front_left_inner_x_mm': max(xf[xf<0]), 'front_right_inner_x_mm': min(xf[xf>0]),
        'front_outer_x_mm': [min(xf),max(xf)], 'rear_barrel_x_mm': [min(xr),max(xr)],
        'left_axial_gap_mm': min(xr)-max(xf[xf<0]),
        'right_axial_gap_mm': min(xf[xf>0])-max(xr),
        'front_outer_span_mm': max(xf)-min(xf),
        'retained_axle_endplay_mm': 52.0-(max(xf)-min(xf)),
        'M5_washer_overlap_on_D6_shoulder_radial_mm': (6-5.3)/2,
        'thread_beyond_locknut_mm': 9.5-1-5,
    }
    report['retention_dimensions'] = measurements
    require(min(measurements['left_axial_gap_mm'],measurements['right_axial_gap_mm'])>.65, 'Ear axial gap too small')
    require(.8<measurements['retained_axle_endplay_mm']<1.2, 'Axle could clamp ears or has excessive nominal endplay')
    # Pin motion is limited by the large washer/head on the left and washer/
    # locknut on the right. A 2 mm escape in either direction must hit an ear.
    report['retention_escape_controls'] = []
    for direction, name in ((2,HARDWARE_NAMES[1]),(-2,HARDWARE_NAMES[2])):
        v,f=data[name]
        moved=v+np.array([direction,0,0])
        overlaps=len(trees[front].overlap(tree(moved,f)))
        report['retention_escape_controls'].append({'translation_mm':direction,'part':name,'surface_pairs':overlaps})
        require(overlaps>0,'Retained axle can escape without an ear collision')
    # The geometry engine must reject an oversized D8 axle and reverse opening.
    control=tube('Oversize control',-25,25,4);control.location=Vector(AXIS/1000);bpy.context.view_layer.update()
    cv,cf=arrays(control)
    oversized=len(trees[front].overlap(tree(cv,cf)))
    mesh=control.data;bpy.data.objects.remove(control,do_unlink=True);bpy.data.meshes.remove(mesh)
    reverse=len(trees[front].overlap(tree(rotated(data[rear][0],-5),data[rear][1])))
    report['negative_controls']={'oversized_D8_axle_pairs':oversized,'reverse_opening_5deg_pairs':reverse}
    require(oversized>0 and reverse>0,'Collision negative control failed')
    report['motion'] = []
    angles=np.linspace(0,CHECKED_ANGLE,math.ceil(CHECKED_ANGLE/args.step)+1)
    start=time.perf_counter()
    for index,angle in enumerate(angles):
        points=rotated(data[rear][0],float(angle));bvh=tree(points,data[rear][1]);sample=rotated(seeds[rear],float(angle))
        collisions={}
        for name in (front,*HARDWARE_NAMES,*fixed_side):
            hit=collision(trees[name],bvh,seeds[name],sample)
            if any(hit.values()):collisions[name]=hit
        for moving_name in moving_side:
            moving_points=rotated(data[moving_name][0],float(angle))
            moving_tree=tree(moving_points,data[moving_name][1])
            moving_seeds=rotated(seeds[moving_name],float(angle))
            for fixed_name in (front,*HARDWARE_NAMES,*fixed_side):
                hit=collision(trees[fixed_name],moving_tree,seeds[fixed_name],moving_seeds)
                if any(hit.values()):collisions[moving_name+' vs '+fixed_name]=hit
        report['motion'].append({'angle_deg':float(angle),'collisions':collisions})
        require(not collisions,f'Motion collision at {angle} degrees: {collisions}')
        if index%40==0:
            print(f'MOTION {index+1}/{len(angles)} angle={angle:.2f}, errors={len(report["errors"])}',flush=True)
            args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    report['motion_seconds']=round(time.perf_counter()-start,3)
    report['solid_intersections']=[boolean_intersection_volume(data[front],data[rear],deg) for deg in (0,40,75,80)]
    for item in report['solid_intersections']:
        require(item['intersection_volume_mm3']<1e-6,'Nonzero shell intersection volume at '+str(item['angle_deg']))
    report['passed']=not report['errors']
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    if report['errors']:
        raise RuntimeError(report['errors'])
    print(f'PASS: {len(angles)} motion poses; insertion/access, retention and topology verified in CAD',flush=True)


if __name__=='__main__':
    main()
