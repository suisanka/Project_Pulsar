"""Read back a saved headform study and render actual mesh intersections."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0,str(Path(__file__).resolve().parent))
from hinge_common import arrays, mesh_object, SHELL_NAMES
from render_cross_sections import contours


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt',type=Path,required=True)
    parser.add_argument('--images',type=Path,required=True)
    parser.add_argument('--validation',type=Path,required=True)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    report=json.loads(args.receipt.read_text())
    if hashlib.sha256(Path(bpy.data.filepath).read_bytes()).hexdigest()!=report['study_sha256']:
        raise ValueError('Saved study hash mismatch')
    scene=bpy.context.scene;args.images.mkdir(parents=True,exist_ok=True)
    scene.render.resolution_x=scene.render.resolution_y=1200
    scene.display.shading.color_type='MATERIAL';scene.world.color=(.87,.9,.92)
    scene.camera.data.ortho_scale=.36
    target=Vector((0,0,.0));scene.camera.location=target+Vector((1,.1,.08))
    scene.camera.rotation_euler=(target-scene.camera.location).to_track_quat('-Z','Y').to_euler()
    def material(name,color):
        mat=bpy.data.materials.new(name);mat.diffuse_color=color;return mat
    green=material('Study_green',(.2,.72,.57,1));red=material('Actual_intersection',(.9,.13,.16,1))
    shell_mats=[material('Study_front',(.3,.6,.8,1)),material('Study_rear',(.85,.57,.26,1))]
    source={name:arrays(name+'_FIT_REFERENCE') for name in SHELL_NAMES}
    trees={name:BVHTree.FromPolygons(v,f,all_triangles=True) for name,(v,f) in source.items()}
    for o in scene.objects:o.hide_render=True
    clipped=[]
    for i,(name,(v,f)) in enumerate(source.items()):
        obj=mesh_object(name+'_DISPLAY_HALF',v,f);obj.data.materials.append(shell_mats[i])
        bm=bmesh.new();bm.from_mesh(obj.data)
        bmesh.ops.bisect_plane(bm,geom=[*bm.verts,*bm.edges,*bm.faces],dist=1e-8,
                              plane_co=(0,0,0),plane_no=(1,0,0),clear_outer=True)
        bm.to_mesh(obj.data);bm.free();obj.data.update();clipped.append(obj)
    validation={'study_sha256':report['study_sha256'],'cases':[]}
    for case in report['cases']:
        label=case['label'];collection=bpy.data.collections['Headform_'+label]
        collection.hide_viewport=False;collection.hide_render=False
        obj=bpy.data.objects['SM_Headform_'+label];obj.hide_render=False
        obj.data.materials.clear();obj.data.materials.append(green);obj.data.materials.append(red)
        v,f=arrays(obj)
        tree=BVHTree.FromPolygons(v,f,all_triangles=True)
        hit_faces=set()
        overlap={}
        for name,shell in trees.items():
            pairs=tree.overlap(shell);overlap[name]=len(pairs)
            if len(pairs)!=case['contacts'].get(name,{}).get('intersecting_triangle_pairs',0):
                raise ValueError('Saved head placement does not reproduce collision count')
            hit_faces.update(i for i,_ in pairs)
        for poly in obj.data.polygons:poly.material_index=1 if poly.index in hit_faces else 0
        loops=contours(v,f,2,case['girth_z_mm'])
        circumference=sum(sum(((a[0]-b[0])**2+(a[1]-b[1])**2)**.5 for a,b in zip(loop,loop[1:]+loop[:1])) for loop in loops)
        dimensions=(v.max(0)-v.min(0)).tolist()
        if abs(circumference-590)>.01 or abs(dimensions[0]-135)>.01 or abs(dimensions[2]-230)>.01:
            raise ValueError('Saved head dimensions do not match requested measurements')
        for half in clipped:half.hide_render=False
        scene.render.filepath=str(args.images/f'headform-{label.lower()}-cutaway.png');bpy.ops.render.render(write_still=True)
        for half in clipped:half.hide_render=True
        # Thin wire overlay avoids the skill review renderer's thick bevel
        # artifacts at the intentional pointed chin and pole triangles.
        wire=obj.copy();wire.data=obj.data.copy();scene.collection.objects.link(wire)
        wire.data.materials.clear();wire.data.materials.append(material('Thin_wire_'+label,(.02,.03,.03,1)))
        for poly in wire.data.polygons:poly.material_index=0
        modifier=wire.modifiers.new('Thin topology overlay','WIREFRAME');modifier.thickness=.00008;modifier.use_even_offset=False;modifier.offset=1
        scene.render.filepath=str(args.images/f'headform-{label.lower()}-topology.png');bpy.ops.render.render(write_still=True)
        bpy.data.objects.remove(wire,do_unlink=True)
        validation['cases'].append({'label':label,'dimensions_mm':dimensions,'girth_mm':circumference,
                                    'reproduced_shell_intersections':overlap,'highlighted_head_triangles':len(hit_faces)})
        obj.hide_render=True;collection.hide_render=True
    validation['passed']=True
    args.validation.write_text(json.dumps(validation,ensure_ascii=False,indent=2)+'\n')
    print('PASS: saved dimensions and collisions reproduced; source study not saved',flush=True)


if __name__=='__main__':main()
