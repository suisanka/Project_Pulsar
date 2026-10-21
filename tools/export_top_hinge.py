"""Export accepted hinge-v2 shells, spacer and closed cropped test coupons.

Requires a passing validate_top_hinge receipt for the exact input .blend SHA.
Purchased metal hardware and the unused legacy R pin are never exported.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hinge_common import AXIS, SHELL_NAMES, SPACER_NAME, arrays, mesh_object
from validate_model import evaluated_metrics, export_stl, failures


def cropped_coupon(name, bounds=None, suffix='Fit_Coupon'):
    vertices, faces = arrays(name)
    source = mesh_object('Coupon source', vertices, faces)
    lo, hi = (np.array([-36., 30., 126.]), np.array([40., 82., 165.])) if bounds is None else tuple(np.array(v,dtype=float) for v in bounds)
    corners = [(x,y,z) for x in (lo[0],hi[0]) for y in (lo[1],hi[1]) for z in (lo[2],hi[2])]
    cube = mesh_object('Coupon crop', corners, [(0,1,3,2),(4,6,7,5),(0,4,5,1),(2,3,7,6),(0,2,6,4),(1,5,7,3)])
    obj = mesh_object('Coupon intersection', [], [])
    group = bpy.data.node_groups.new('Coupon closed intersection', 'GeometryNodeTree')
    group.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    modifier = obj.modifiers.new('Closed intersection', 'NODES'); modifier.node_group = group
    boolean = group.nodes.new('GeometryNodeMeshBoolean'); boolean.operation='INTERSECT'; boolean.solver='MANIFOLD'
    for item in (source,cube):
        node=group.nodes.new('GeometryNodeObjectInfo');node.inputs['Object'].default_value=item
        group.links.new(node.outputs['Geometry'],boolean.inputs[1])
    end=group.nodes.new('NodeGroupOutput');group.links.new(boolean.outputs[0],end.inputs[0])
    bpy.context.view_layer.update()
    points,triangles=arrays(obj)
    # Translate only: both coupons retain the assembly orientation, with flat
    # cut bottom at Z=0. The actual mechanical mating surfaces are untouched.
    offset=np.array([(lo[0]+hi[0])/2,(lo[1]+hi[1])/2,lo[2]])
    frozen=mesh_object(name+'_'+suffix,points-offset,triangles)
    for item in (source,cube,obj):
        mesh=item.data;bpy.data.objects.remove(item,do_unlink=True);bpy.data.meshes.remove(mesh)
    bpy.data.node_groups.remove(group)
    return frozen, {'clip_min_world_mm':lo.tolist(),'clip_max_world_mm':hi.tolist(),'translation_mm':(-offset).tolist()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validation',type=Path,required=True)
    parser.add_argument('--exports',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--side-validation',type=Path)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    digest=hashlib.sha256(Path(bpy.data.filepath).read_bytes()).hexdigest()
    receipt=json.loads(args.validation.read_text())
    if not receipt.get('passed') or receipt['blend_sha256']!=digest:
        raise ValueError('A passing assembly receipt for this exact saved file is required')
    side_revision=bpy.context.scene.get('pulsar_side_latch_revision')
    if side_revision:
        if not args.side_validation:raise ValueError('--side-validation is required for the screw-mounted latch version')
        side=json.loads(args.side_validation.read_text())
        if not side.get('passed') or side['blend_sha256']!=digest:raise ValueError('Side-latch receipt does not match this file')
    args.exports.mkdir(parents=True,exist_ok=True);args.manifest.parent.mkdir(parents=True,exist_ok=True)
    manifest={'blend_sha256':digest,'units':'mm','assembly_validation_sha256':hashlib.sha256(args.validation.read_bytes()).hexdigest(),'files':[],
              'excluded':'Purchased shoulder axle, washers, nut, helper cutters and unused legacy R pin.'}
    def export(name,filename,role,transform=None):
        path=args.exports/filename
        source=evaluated_metrics(name);result=export_stl(name,path)
        if failures(source) or failures(result):raise ValueError((name,failures(source),failures(result)))
        manifest['files'].append({'path':str(path),'role':role,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size,
                                  'source_metrics':source,'stl_metrics':result,'export_transform':transform})
        print('EXPORTED',filename,flush=True)
    version=('Closure_v4' if side_revision>=2 else 'Closure_v3') if side_revision else 'Hinge_v2'
    export(SHELL_NAMES[0],f'ProjectPulsar_Front_{version}.stl','front shell')
    export(SHELL_NAMES[1],f'ProjectPulsar_Rear_{version}.stl','rear shell')
    points,faces=arrays(SPACER_NAME);points-=AXIS
    points=points[:,[1,2,0]]-np.array([0,0,26.0])
    spacer=mesh_object('Spacer print orientation',points,faces)
    export(spacer.name,'ProjectPulsar_Hinge_Spacer_1p4.stl','print one; flat on bed',{'axis_mapping':'assembly (Y,Z,X) -> print (X,Y,Z); bottom Z=0'})
    for name,label in zip(SHELL_NAMES,('Front','Rear')):
        coupon,transform=cropped_coupon(name)
        export(coupon.name,f'ProjectPulsar_Hinge_Test_{label}.stl','local fit coupon; not the full shell',transform)
    if side_revision:
        manifest['side_validation_sha256']=hashlib.sha256(args.side_validation.read_bytes()).hexdigest()
        for name,label in zip(SHELL_NAMES,('Front','Rear')):
            coupon,transform=cropped_coupon(name,([-125,-50,5],[-80,20,65]),'Side_Latch_Coupon')
            export(coupon.name,f'ProjectPulsar_SideLatch_Test_{label}_L.stl','left-side latch fit coupon; both sides use the same mirrored 20x20 pattern',transform)
    manifest['passed']=True
    args.manifest.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(f'PASS: {len(manifest["files"])} printable STLs re-read and verified',flush=True)


if __name__=='__main__':main()
