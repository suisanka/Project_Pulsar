"""Render real saved geometry, head envelopes, sections and source STL views.

This is read-only for all .blend/STL inputs. Analysis cutaways are not printable
parts. All comparison cameras share the same framing and orthographic scale.
"""

import argparse
import json
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hinge_common import SHELL_NAMES, arrays, mesh_object, rotated
from render_cross_sections import contours
from test_headform_fit import head_mesh, solve_depth


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--receipt', type=Path, required=True)
    p.add_argument('--reference-front', type=Path, required=True)
    p.add_argument('--reference-rear', type=Path, required=True)
    a = p.parse_args(sys.argv[sys.argv.index('--')+1:])
    after = {n: arrays(n) for n in SHELL_NAMES}
    bpy.ops.wm.open_mainfile(filepath=str(a.base.resolve()), load_ui=False)
    before = {n: arrays(n) for n in SHELL_NAMES}
    s = bpy.data.scenes.new('Reference fit review')
    bpy.context.window.scene = s
    s.render.engine = 'BLENDER_WORKBENCH'
    s.render.resolution_x = 900
    s.render.resolution_y = 900
    s.render.resolution_percentage = 100
    s.render.image_settings.file_format = 'PNG'
    s.view_settings.view_transform = 'Standard'
    s.display.shading.light = 'STUDIO'
    s.display.shading.color_type = 'OBJECT'
    s.display.shading.show_shadows = False
    s.display.shading.show_cavity = True
    s.display.shading.cavity_type = 'BOTH'
    s.display.shading.background_type = 'WORLD'
    s.world = bpy.data.worlds.new('Reference fit background')
    s.world.color = (.91, .93, .95)
    cam = bpy.data.objects.new('ReferenceFit_Camera', bpy.data.cameras.new('ReferenceFit_Camera'))
    s.collection.objects.link(cam)
    s.camera = cam
    cam.data.type = 'ORTHO'
    a.output.mkdir(parents=True, exist_ok=True)
    objects = {}
    for label, data, color in [('front', after[SHELL_NAMES[0]], (.32, .64, .82, 1)),
                               ('before', before[SHELL_NAMES[1]], (.63, .66, .69, 1)),
                               ('after', after[SHELL_NAMES[1]], (.86, .58, .28, 1))]:
        obj = mesh_object('Review_'+label, *data)
        obj.color = color
        obj.hide_render = True
        for face in obj.data.polygons:
            face.use_smooth = True
        objects[label] = obj
        half = obj.copy()
        half.data = obj.data.copy()
        s.collection.objects.link(half)
        bm = bmesh.new()
        bm.from_mesh(half.data)
        bmesh.ops.bisect_plane(bm, geom=[*bm.verts, *bm.edges, *bm.faces], dist=1e-8,
                              plane_co=(0, 0, 0), plane_no=(1, 0, 0), clear_outer=True)
        bm.to_mesh(half.data)
        bm.free()
        half.data.update()
        objects[label+'_half'] = half
    hv, hf = head_mesh(2, solve_depth(2))
    hv += [0, -27, -136]
    head = mesh_object('Review_Envelope_Ellipse', hv, hf)
    head.color = (.29, .72, .58, 1)
    head.hide_render = True
    for face in head.data.polygons:
        face.use_smooth = True
    objects['head'] = head
    opened = mesh_object('Review_Rear_Open75', rotated(after[SHELL_NAMES[1]][0], 75), after[SHELL_NAMES[1]][1])
    opened.color = objects['after'].color
    opened.hide_render = True
    for face in opened.data.polygons:
        face.use_smooth = True
    objects['open'] = opened

    def render(name, visible, direction=(1, 0, 0), target=(0, -.015, .01), scale=.37):
        for key, obj in objects.items():
            obj.hide_render = key not in visible
        center = Vector(target)
        cam.location = center + Vector(direction).normalized()
        cam.rotation_euler = (center-cam.location).to_track_quat('-Z', 'Y').to_euler()
        cam.data.ortho_scale = scale
        s.render.filepath = str(a.output/(name+'.png'))
        bpy.ops.render.render(write_still=True)

    for label in ('before', 'after'):
        render('reference-fit-'+label+'-side', ['front', label])
        render('reference-fit-'+label+'-cutaway', ['front_half', label+'_half', 'head'])
    render('reference-fit-after-quarter', ['front', 'after'], (1, 1, .3))
    render('reference-fit-after-back', ['front', 'after'], (1, -1, .3))
    render('reference-fit-open75', ['front', 'open', 'head'], (1, .05, .05), (0, -.075, .07), .5)
    wire = objects['after'].copy()
    wire.data = wire.data.copy()
    s.collection.objects.link(wire)
    wire.color = (.02, .025, .03, 1)
    mod = wire.modifiers.new('QA thin wire', 'WIREFRAME')
    mod.thickness = .000008
    mod.use_even_offset = False
    mod.offset = 1
    objects['wire'] = wire
    render('reference-fit-rear-wire', ['after', 'wire'], (1, -1, .3))
    render('reference-fit-rear-wire-inside', ['after', 'wire'], (0, 1, 0))
    references = []
    for label, path, color in [('ref-front', a.reference_front, (.32, .64, .82, 1)),
                                ('ref-rear', a.reference_rear, (.86, .58, .28, 1))]:
        data = path.read_bytes()
        records = np.frombuffer(data, dtype=[('normal', '<f4', 3), ('vertices', '<f4', (3, 3)), ('attr', '<u2')], offset=84)
        v, ix = np.unique(records['vertices'].reshape(-1, 3), axis=0, return_inverse=True)
        f = ix.reshape(-1, 3)
        obj = mesh_object(label, v, f)
        obj.color = color
        objects[label] = obj
        for face in obj.data.polygons:
            face.use_smooth = True
        target = (v.min(0)+v.max(0))/2000
        scale = float(np.ptp(v, axis=0).max())*.00125
        for view, direction in [('outside', (0, 0, 1)), ('inside', (0, 0, -1))]:
            render(label+'-'+view, [label], direction, target, scale)
        references.append({'name': path.name, 'bounds_original_stl_axes': [v.min(0).tolist(), v.max(0).tolist()]})
    depths = []
    for z in (-60, 0, 80):
        row = {'z_mm': z}
        for label, data in [('before', before), ('after', after)]:
            hits = []
            for name, direction in zip(SHELL_NAMES, ((0, 1, 0), (0, -1, 0))):
                tree = BVHTree.FromPolygons(*data[name], all_triangles=True)
                hit = tree.ray_cast((0, 0, z), direction, 500)[0]
                hits.append(list(hit) if hit is not None else None)
            row[label] = {'hits_mm': hits, 'clear_depth_mm': hits[0][1]-hits[1][1] if all(p is not None for p in hits) else None}
        depths.append(row)
    record = {'references': references, 'centerline_depths': depths,
              'side_sections': {label: [contours(*data[n], 0, 0) for n in SHELL_NAMES]
                                for label, data in [('before', before), ('after', after)]},
              'head_outline': contours(hv, hf, 0, 0),
              'scope': 'Shell-only X=0 ray measurements; hardware/liner excluded. Cutaways are illustrative meshes.'}
    a.receipt.write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n')
    print('DEPTHS', json.dumps(depths), flush=True)


if __name__ == '__main__':
    main()
