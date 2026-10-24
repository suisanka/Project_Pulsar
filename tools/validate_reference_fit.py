"""Independently validate the saved reference-fit variant and head envelopes.

The clearance certificate covers triangle interiors using the 1-Lipschitz
distance bound, recursively refining uncertain faces. It is a geometric result
for two assumed head shapes, not a scan, pressure or physical comfort test.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_front_thickness import mesh_digest
from hinge_common import HARDWARE_NAMES, SHELL_NAMES, arrays, mesh_object, rotated
from test_headform_fit import head_mesh, pupil_positions, solve_depth
from validate_model import evaluated_metrics, failures, triangle_metrics
from validate_top_hinge import inside


def certificate(vertices, faces, obstacle, target=7.0, max_depth=7):
    triangles = vertices[faces]
    lower, minimum, queries = float('inf'), float('inf'), 0
    for depth in range(max_depth+1):
        centers = triangles.mean(1)
        radii = np.linalg.norm(triangles-centers[:, None, :], axis=2).max(1)
        distances = np.array([obstacle.find_nearest(p)[3] for p in centers])
        queries += len(distances)
        minimum = min(minimum, float(distances.min()))
        if distances.min() < target + .001:
            return {'passed': False, 'sample_min_mm': minimum, 'queries': queries, 'depth': depth}
        bounds = distances-radii-.001
        complete = bounds >= target
        if complete.any():
            lower = min(lower, float(bounds[complete].min()))
        pending = triangles[~complete]
        if not len(pending):
            return {'passed': True, 'certified_lower_bound_mm': lower,
                    'sample_min_mm': minimum, 'queries': queries, 'depth': depth,
                    'numeric_allowance_mm': .001}
        if depth == max_depth:
            break
        a, b, c = pending[:, 0], pending[:, 1], pending[:, 2]
        ab, bc, ca = (a+b)/2, (b+c)/2, (c+a)/2
        triangles = np.concatenate([np.stack(t, axis=1) for t in
                                    ((a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca))])
    return {'passed': False, 'unresolved_triangles': len(pending), 'sample_min_mm': minimum, 'queries': queries}


def combined_tree(data):
    points, faces, offset = [], [], 0
    for v, f in data:
        points.append(v)
        faces.append(f+offset)
        offset += len(v)
    return BVHTree.FromPolygons(np.concatenate(points), np.concatenate(faces), all_triangles=True)


def swept_hull(v, travel_mm=350):
    """Convex superset of every point during straight rear-to-front insertion."""
    bm = bmesh.new()
    for p in np.concatenate((v, v-np.array([0, travel_mm, 0]))):
        bm.verts.new(p)
    bmesh.ops.convex_hull(bm, input=list(bm.verts), use_existing_faces=False)
    # Interior source points are unused; only the hull faces are inspected.
    bmesh.ops.triangulate(bm, faces=list(bm.faces))
    bm.verts.index_update()
    vertices = np.array([tuple(p.co) for p in bm.verts])
    faces = np.array([[p.index for p in face.verts] for face in bm.faces], dtype=np.int32)
    bm.free()
    ids, remap = np.unique(faces, return_inverse=True)
    return vertices[ids], remap.reshape(-1, 3)


def wall_samples(before, after):
    v0, f = before
    v1, f1 = after
    if not np.array_equal(f, f1):
        raise ValueError('Expansion changed topology')
    trees = [BVHTree.FromPolygons(v, f, all_triangles=True) for v in (v0, v1)]
    p = v0[f]
    normals = np.cross(p[:, 1]-p[:, 0], p[:, 2]-p[:, 0])
    normals /= np.linalg.norm(normals, axis=1)[:, None]
    rows = []
    for index in range(0, len(f), 19):
        if v0[f[index], 1].mean() >= -45:
            continue
        row = []
        for vertices, tree in zip((v0, v1), trees):
            tri = vertices[f[index]]
            c = tri.mean(0)
            n = np.cross(tri[1]-tri[0], tri[2]-tri[0])
            n /= np.linalg.norm(n)
            hit, other_normal, other, distance = tree.ray_cast(c-n*.0001, -n, 30)
            row.append(distance+.0001 if hit is not None and np.dot(-n, other_normal) > 0
                       and np.dot(normals[index], normals[other]) < -.8 else None)
        if row[0] is not None and 2.2 <= row[0] <= 3.2 and row[1] is not None:
            rows.append({'face': index, 'before_mm': row[0], 'after_mm': row[1]})
    if not rows or min(r['after_mm'] for r in rows) < 2.2:
        raise ValueError('Rear sampled wall thickness failed')
    return rows


def inherited_coplanar_pairs(qa_obj, original, qa_check, eps=1e-5):
    """Locate generic QA pairs and require exact baseline STL triangles.

    Never waive a new overlap. Preserve the raw QA result; this only classifies
    the unchanged legacy hinge pair separately from this revision's changes.
    """
    vertices = [v.co.copy() for v in qa_obj.data.vertices]
    faces = [tuple(p.vertices) for p in qa_obj.data.polygons]
    tree = BVHTree.FromPolygons(vertices, faces, all_triangles=True)
    normals = [(vertices[b]-vertices[a]).cross(vertices[c]-vertices[a]).normalized() for a, b, c in faces]
    sets = list(map(set, faces))
    pairs = set()
    for i, face in enumerate(faces):
        a, b, c = [vertices[k] for k in face]
        center = (a+b+c)/3
        n = normals[i]
        for p in (center, center.lerp(a, .6), center.lerp(b, .6), center.lerp(c, .6)):
            for _, _, j, _ in tree.find_nearest_range(p, eps):
                if j is None or i == j or sets[i] & sets[j] or n.dot(normals[j]) < .999:
                    continue
                a2, b2, c2 = [vertices[k] for k in faces[j]]
                q = p-normals[j]*normals[j].dot(p-a2)
                if qa_check._point_in_tri(q, a2, b2, c2, normals[j]):
                    pairs.add(tuple(sorted((i, j))))
    def key(triangle):
        return tuple(sorted(tuple(float(x) for x in p) for p in triangle))
    # Match the millimetre float32 coordinates actually used by the QA copy.
    base_obj = mesh_object('QA_Baseline_For_Pair_Identity', original[0]*1000, original[1])
    base_v = np.array([tuple(v.co) for v in base_obj.data.vertices])
    original_faces = {key(triangle) for triangle in base_v[original[1]]}
    records = []
    for i, j in sorted(pairs):
        triangles = [[tuple(vertices[k]) for k in faces[index]] for index in (i, j)]
        records.append({'face_indices': [i, j], 'triangles_mm': triangles,
                        'both_triangles_identical_to_baseline': all(key(t) in original_faces for t in triangles)})
    return records


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--qa-scripts', type=Path, required=True)
    args = p.parse_args(sys.argv[sys.argv.index('--')+1:])
    variant = Path(bpy.data.filepath).resolve()
    digest = hashlib.sha256(variant.read_bytes()).hexdigest()
    if bpy.context.scene.get('pulsar_reference_fit_revision') != 1:
        raise ValueError('Load the reference-fit variant')
    names = [*SHELL_NAMES, *HARDWARE_NAMES, *[o.name for o in bpy.data.objects if 'pulsar_attached_shell' in o]]
    # Inspect the repository's actual attached-shell tag values below; unknown
    # values must not silently leave rear hardware in the closed pose.
    tags = {o.name: o['pulsar_attached_shell'] for o in bpy.data.objects if 'pulsar_attached_shell' in o}
    moving_names = [SHELL_NAMES[1], *[n for n, shell in tags.items() if shell in ('rear', SHELL_NAMES[1])]]
    if any(shell not in ('rear', 'front', *SHELL_NAMES) for shell in tags.values()):
        raise ValueError(('Unknown hardware attachment tag', tags))
    current = {name: arrays(name) for name in names}
    metrics = {name: evaluated_metrics(name) for name in SHELL_NAMES}
    if any(failures(m) for m in metrics.values()):
        raise ValueError(metrics)
    rear = bpy.data.objects[SHELL_NAMES[1]]
    expansion = next(m for m in rear.modifiers if m.name.startswith('后脑空间'))
    expansion.show_viewport = False
    bpy.context.view_layer.update()
    relief = arrays(rear)
    expansion.show_viewport = True
    bpy.context.view_layer.update()
    samples = wall_samples(relief, current[SHELL_NAMES[1]])
    print('WALL', len(samples), min(r['after_mm'] for r in samples), max(r['after_mm'] for r in samples), flush=True)
    bpy.ops.wm.open_mainfile(filepath=str(args.base.resolve()), load_ui=False)
    original = {name: arrays(name) for name in names}
    unchanged = {n: mesh_digest(original[n]) == mesh_digest(current[n]) for n in names if n != SHELL_NAMES[1]}
    if not all(unchanged.values()):
        raise ValueError(('Unexpected changed part', unchanged))
    # All analysis objects below live in this unsaved temporary session.
    trees = {name: BVHTree.FromPolygons(*data, all_triangles=True) for name, data in current.items()}
    whole = combined_tree(current.values())
    opened = {name: (rotated(v, 75), f) if name in moving_names else (v, f)
              for name, (v, f) in current.items()}
    open_trees = {name: BVHTree.FromPolygons(*data, all_triangles=True) for name, data in opened.items()}
    cases = []
    for exponent in (2, 3):
        depth = solve_depth(exponent)
        v, f = head_mesh(exponent, depth)
        offset = np.array([0., -27., -136.])
        v += offset
        tree = BVHTree.FromPolygons(v, f, all_triangles=True)
        contacts = {}
        for name, obstacle in trees.items():
            pairs = len(tree.overlap(obstacle))
            contained = inside(obstacle, v[0]) or inside(tree, current[name][0][0])
            if pairs or contained:
                contacts[name] = {'pairs': pairs, 'containment': bool(contained)}
        clear = certificate(v, f, whole)
        eyes = pupil_positions(exponent, depth, offset)
        rays = [{'origin_mm': eye.tolist(), 'blocked': trees[SHELL_NAMES[0]].ray_cast(eye, (0, 1, 0), 400)[0] is not None}
                for eye in eyes]
        swept_v, swept_f = swept_hull(v)
        sweep = BVHTree.FromPolygons(swept_v, swept_f, all_triangles=True)
        sweep_contacts = {}
        for name, obstacle in open_trees.items():
            pairs = len(sweep.overlap(obstacle))
            contained = inside(sweep, opened[name][0][0]) or inside(obstacle, swept_v[0])
            if pairs or contained:
                sweep_contacts[name] = {'pairs': pairs, 'containment': bool(contained)}
        swing_contacts = []
        for angle in range(0, 76, 5):
            for name in moving_names:
                av, af = current[name]
                rotated_v = rotated(av, angle)
                obstacle = BVHTree.FromPolygons(rotated_v, af, all_triangles=True)
                pairs = len(tree.overlap(obstacle))
                if pairs or inside(obstacle, v[0]) or inside(tree, rotated_v[0]):
                    swing_contacts.append({'angle': angle, 'part': name, 'pairs': pairs})
        row = {'exponent': exponent, 'implied_depth_mm': depth, 'offset_xyz_mm': offset.tolist(),
               'head_metrics': triangle_metrics(v, f), 'contacts': contacts, 'clearance': clear,
               'pupil_rays': rays, 'rear_swing': {'step_deg': 5, 'range_deg': [0, 75], 'contacts': swing_contacts},
               'entry': {'rear_open_angle_deg': 75, 'translation_mm': [0, 350, 0],
                         'method': 'Convex hull of both endpoints conservatively encloses the full continuous straight translation',
                         'swept_hull_metrics': triangle_metrics(swept_v, swept_f), 'contacts': sweep_contacts}}
        row['passed'] = (not contacts and clear['passed'] and not any(r['blocked'] for r in rays)
                         and not sweep_contacts and not swing_contacts)
        cases.append(row)
        print('FIT', exponent, json.dumps({k: row[k] for k in ('passed', 'clearance', 'rear_swing', 'entry')})[:2500], flush=True)
    sys.path.insert(0, str(args.qa_scripts.resolve()))
    import qa_check
    v, f = current[SHELL_NAMES[1]]
    qa_obj = mesh_object('QA_ReferenceFit_Rear_mm', v*1000, f)
    qa = qa_check.run(objects=[qa_obj.name], profile='print', uv=False, eps=1e-5, tol=.001)
    pairs = inherited_coplanar_pairs(qa_obj, original[SHELL_NAMES[1]], qa_check) if qa['zfighting'] else []
    inherited_only = (bool(pairs) and all(p['both_triangles_identical_to_baseline'] for p in pairs)
                      and len(pairs) == sum(row['tri_pairs'] for row in qa['zfighting']))
    blocking_qa = [error for error in qa['errors']
                   if not (error.startswith('z-fighting:') and inherited_only)]
    report = {'blend_sha256': digest, 'base_sha256': hashlib.sha256(args.base.read_bytes()).hexdigest(),
              'blender': bpy.app.version_string, 'unchanged_parts': unchanged, 'metrics': metrics,
              'head_measurements_mm': {'height': 230, 'width_without_ears': 135, 'girth': 590,
                                       'pupil_height_from_chin': 127, 'ipd': 65},
              'assumptions': {'head_shapes': 'Existing exponent-2 ellipse and exponent-3 rounded envelope; no anatomy scan',
                              'girth_height_from_chin_mm': 157, 'pose': 'upright; X centered; eyes Z=-9 mm',
                              'clearance_target_mm': 7, 'padding_budget_mm': 5, 'extra_budget_mm': 2},
              'cases': cases, 'rear_wall_samples': samples,
              'rear_wall_sample_range_mm': [min(r['after_mm'] for r in samples), max(r['after_mm'] for r in samples)],
              'wall_method': 'Normal rays on matching faces before/after expansion; original skin pairs 2.2-3.2 mm only, vent sidewalls excluded',
              'qa': qa, 'inherited_coplanar_pairs': pairs, 'blocking_qa_errors': blocking_qa,
              'qa_scope': 'Raw full-rear QA is retained. Only exactly baseline-identical coplanar triangles are accepted as inherited findings; any new pair or other error blocks.',
              'accepted_warnings': ['STL has no material/UV requirement; assembly coordinates intentionally retained.',
                                    'One inherited hinge coplanar pair is retained; both triangles match the baseline exactly. Full generic QA pass is not claimed.'],
              'limits': ['The wearer head length, ears, nose, hair and neck/shoulders are not reconstructed.',
                         'Entry proof covers only these head meshes, rigid translation with rear held at 75 degrees, and modeled hardware.',
                         'Rear-to-head swing is sampled every 5 degrees; not a continuous collision certificate.',
                         'No physical print, liner compression, ventilation, latch-cover CAD, fatigue or wearer trial.',
                         'Wall readings are sampled, not a global minimum thickness guarantee.']}
    report['passed'] = all(c['passed'] for c in cases) and not blocking_qa
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    if hashlib.sha256(variant.read_bytes()).hexdigest() != digest:
        raise RuntimeError('Variant file changed during read-only checks')
    if not report['passed']:
        raise RuntimeError(('Reference fit validation failed', qa['errors'], [c['passed'] for c in cases]))
    print('PASS: saved-model fit, no new QA errors, clearance and conservative head-entry checks', flush=True)


if __name__ == '__main__':
    main()
