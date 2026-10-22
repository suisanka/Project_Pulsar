"""Check the saved thickness variant, inherited cavities and multi-angle views.

Asset QA runs on individual closed surfaces in millimetre coordinates. This
avoids treating the generic metre-scale 10-micron merge tolerance as duplicate
STL vertices. Inherited, inward-facing ear cavities are compared exactly with
the base, then reversed ONLY on temporary standalone QA copies. The exported
shell keeps their correct cavity winding. Full-shell STL topology is checked
independently by validate_model and the assembly export pipeline.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_front_thickness import mesh_digest
from hinge_common import arrays, mesh_object
from validate_model import evaluated_metrics, failures


def components(mesh):
    points, faces = mesh
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
    groups = np.array([root(i) for i in range(len(points))])
    result = []
    for key in np.unique(groups):
        triangles = faces[groups[faces[:, 0]] == key]
        ids, inverse = np.unique(triangles, return_inverse=True)
        vertices = points[ids]
        triangles = inverse.reshape(-1, 3)
        p = vertices[triangles]
        volume = np.sum(p[:, 0] * np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])) / 6
        result.append((vertices, triangles, float(volume)))
    return sorted(result, key=lambda item: -abs(item[2]))


def render_review(current, images):
    import review_shots

    names = []
    for name, (points, faces) in current.items():
        obj = mesh_object('Review_' + name, points, faces)
        names.append(obj.name)
    bpy.context.scene.display.shading.show_shadows = False
    review_shots.DIRS.update(face=(0, 1, 0), face_quarter=(1, 1, .35), inside=(0, -1, 0))
    images.mkdir(parents=True, exist_ok=True)
    views = review_shots.run(objects=names, out=str(images / 'front-3mm-review.png'),
                             views=['face', 'face_quarter', 'right', 'top'], mode='random', res=600)
    front = bpy.data.objects[names[0]]
    wire = front.copy()
    wire.data = front.data.copy()
    bpy.context.scene.collection.objects.link(wire)
    wire.name = 'Review_Front_Thin_Wire'
    modifier = wire.modifiers.new('Thin wire without acute-corner spikes', 'WIREFRAME')
    modifier.thickness = .000008
    modifier.use_even_offset = False
    modifier.offset = 1
    for obj, color in ((front, (.75, .75, .75, 1)), (wire, (.01, .01, .01, 1))):
        material = bpy.data.materials.new('QA wire surface')
        material.diffuse_color = color
        obj.data.materials.clear()
        obj.data.materials.append(material)
    wire_views = review_shots.run(objects=[front.name, wire.name],
                                  out=str(images / 'front-3mm-wire.png'),
                                  views=['face', 'inside'], mode='material', res=1000)
    return {'views': views, 'wire_views': wire_views}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--images', type=Path, required=True)
    parser.add_argument('--qa-scripts', type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    variant = Path(bpy.data.filepath).resolve()
    digest = hashlib.sha256(variant.read_bytes()).hexdigest()
    sys.path.insert(0, str(args.qa_scripts.resolve()))
    import qa_check

    bpy.ops.wm.open_mainfile(filepath=str(args.base.resolve()), load_ui=False)
    base = {name: arrays(name) for name in ('前壳配置', '后壳配置')}
    cavities = sorted(mesh_digest((p, f)) for p, f, v in components(base['前壳配置']) if v < 0)
    bpy.ops.wm.open_mainfile(filepath=str(variant), load_ui=False)
    current = {name: arrays(name) for name in base}
    parts = {name: components(mesh) for name, mesh in current.items()}
    current_cavities = sorted(mesh_digest((p, f)) for p, f, v in parts['前壳配置'] if v < 0)
    report = {'blend_sha256': digest, 'blender': bpy.app.version_string,
              'base_sha256': hashlib.sha256(args.base.read_bytes()).hexdigest(),
              'rear_unchanged': mesh_digest(base['后壳配置']) == mesh_digest(current['后壳配置']),
              'four_inherited_ear_cavities_unchanged': len(cavities) == 4 and cavities == current_cavities,
              'qa_coordinate_units': 'mm; identity object scale; independent closed surfaces',
              'qa_thresholds': {'face_area_mm2': 1e-10, 'duplicate_distance_mm': 1e-5,
                                'edge_length_mm': 1e-7, 'coplanar_distance_mm': 1e-5},
              'meshes': {}, 'errors': [], 'inherited_rear_findings': [],
              'scope': 'Changed front passes component QA. Unchanged rear retains its baseline coplanarity findings; full-shell topology and assembly must pass independently.'}
    if not report['rear_unchanged'] or not report['four_inherited_ear_cavities_unchanged']:
        raise ValueError('Rear shell or original ear cavities changed')
    for name, surfaces in parts.items():
        metrics = evaluated_metrics(name)
        if failures(metrics):
            raise ValueError((name, failures(metrics)))
        if sum(volume > 0 for _, _, volume in surfaces) != 1:
            raise ValueError(f'{name}: unexpected detached material components')
        row = {'metrics': metrics, 'components': []}
        for index, (points, faces, volume) in enumerate(surfaces):
            # mesh_object converts mm to metres. Multiply input by 1000 to
            # present explicit mm coordinates to the fixed-threshold QA code.
            obj = mesh_object(f'QA_{name}_{index}', points * 1000,
                              faces[:, ::-1] if volume < 0 else faces)
            result = qa_check.run(objects=[obj.name], profile='print', uv=False,
                                  eps=1e-5, tol=.001)
            row['components'].append({'signed_volume_mm3': volume,
                                      'inherited_cavity': volume < 0, 'qa': result})
            # The task changes the front only. Keep original rear geometry
            # and expose its existing coplanarity findings without claiming
            # that its generic QA passed. All other errors remain blocking.
            for error in result['errors']:
                if name == '后壳配置' and report['rear_unchanged'] and error.startswith('z-fighting:'):
                    report['inherited_rear_findings'].append(error)
                else:
                    report['errors'].append(error)
            mesh = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.meshes.remove(mesh)
        report['meshes'][name] = row
        print('QA', name, 'errors', report['errors'], flush=True)
    report['accepted_warnings'] = [
        'STL has no materials or UVs; missing material slots are expected.',
        'Assembly coordinates are retained; a slicer must place each part on its bed.',
        'The front main surface exceeds the generic 300k-triangle pairwise-check limit. Component count/cavity identity, full-shell topology, side-lock measurements and mechanical motion have separate checks.',
        'Two generic near-coplanar triangle-pair findings remain in the bitwise-equivalent rear mesh. Rear generic coplanarity QA is not claimed to pass; the requested front change does not repair the rear.',
    ]
    report['passed'] = not report['errors']
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    if report['errors']:
        raise RuntimeError(report['errors'])
    report.update(render_review(current, args.images))
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print('PASS: saved variant, inherited cavities, millimetre QA and review renders', flush=True)


if __name__ == '__main__':
    main()
