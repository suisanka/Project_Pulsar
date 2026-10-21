"""Convert both small side-latch seats to 20 x 20 mm M3 through-bolt mounts.

Target: user-supplied 40 x 27 mm locking latch, four D3.5 holes, 0.5 mm plate.
The purchased latch's moving internals are not reproduced by this model.
"""

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hinge_common import arrays, mesh_object, tube
from validate_model import evaluated_metrics, failures, get_input


BASE_POINT = np.array([-.010565, 58.161121, 144.17639])
LOCK_OFFSET_MM = 11.0
HOLES = [(y, z) for y in (-16., 4.) for z in (-10., 10.)]
SEAT_X = 5.6
BACK_X = 9.6


def circular_features(mesh):
    features = []
    for face in mesh.polygons:
        if len(face.vertices) < 8:
            continue
        points = np.array([mesh.vertices[i].co[:] for i in face.vertices])*1000
        origin = points.mean(0)
        _, _, basis = np.linalg.svd(points-origin, full_matrices=False)
        q = (points-origin)@basis[:2].T
        coeff = np.linalg.lstsq(np.column_stack((2*q,np.ones(len(q)))),np.sum(q*q,axis=1),rcond=None)[0]
        center = origin+coeff[:2]@basis[:2]
        radius = np.sqrt(coeff[2]+sum(coeff[:2]**2))
        error = max(abs(np.linalg.norm(points-center,axis=1)-radius))
        if .4<radius<2.3 and error<.05 and max(abs((points-origin)@basis[2]))<.01:
            features.append(center)
    if len(features)!=5:
        raise ValueError('Expected the original four post tips and central circular feature')
    return np.array(features)


def template_transform():
    a = circular_features(bpy.data.objects['小锁结构源'].data)
    b = circular_features(bpy.data.objects['小锁结构'].data)
    u, _, vt = np.linalg.svd((a-a.mean(0)).T@(b-b.mean(0)))
    rotation = vt.T@u.T
    if np.linalg.det(rotation)<0:
        vt[-1]*=-1
        rotation=vt.T@u.T
    translation=b.mean(0)-a.mean(0)@rotation.T
    residual=max(np.linalg.norm(a@rotation.T+translation-b,axis=1))
    if residual>.001:
        raise ValueError('Side-latch template correspondence changed')
    return rotation,translation,float(residual)


def box(name,lo,hi):
    corners=[(x,y,z) for x in (lo[0],hi[0]) for y in (lo[1],hi[1]) for z in (lo[2],hi[2])]
    return mesh_object(name,corners,[(0,1,3,2),(4,6,7,5),(0,4,5,1),(2,3,7,6),(0,2,6,4),(1,5,7,3)])


def transform_template(obj,rotation,translation):
    for vertex in obj.data.vertices:
        vertex.co=(np.array(vertex.co)*1000@rotation.T+translation)/1000
    obj.data.update()


def solid_boolean(objects,operation):
    obj=mesh_object('Side latch work result',[],[])
    group=bpy.data.node_groups.new('Side latch solid operation','GeometryNodeTree')
    group.interface.new_socket(name='Geometry',in_out='OUTPUT',socket_type='NodeSocketGeometry')
    modifier=obj.modifiers.new('Solid operation','NODES');modifier.node_group=group
    boolean=group.nodes.new('GeometryNodeMeshBoolean');boolean.operation=operation;boolean.solver='MANIFOLD'
    for index,item in enumerate(objects):
        node=group.nodes.new('GeometryNodeObjectInfo');node.inputs['Object'].default_value=item
        group.links.new(node.outputs['Geometry'],boolean.inputs[0 if operation=='DIFFERENCE' and index==0 else 1])
    end=group.nodes.new('NodeGroupOutput');group.links.new(boolean.outputs[0],end.inputs[0])
    bpy.context.view_layer.update();points,faces=arrays(obj)
    result=mesh_object('Side latch frozen result',points,faces)
    mesh=obj.data;bpy.data.objects.remove(obj,do_unlink=True);bpy.data.meshes.remove(mesh);bpy.data.node_groups.remove(group)
    return result


def duplicate_local(name):
    source=bpy.data.objects[name]
    points=np.array([v.co[:] for v in source.data.vertices])*1000
    return mesh_object('Side latch local copy',points,[tuple(f.vertices) for f in source.data.polygons])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--receipt',type=Path,required=True)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    scene=bpy.context.scene
    if scene.get('pulsar_side_latch_revision'):
        raise ValueError('Side-latch revision already installed')
    if get_input('前壳配置','锁类型')!=1 or abs(get_input('前壳配置','前后基准值')-.78)>1e-6:
        raise ValueError('Build on the documented default small-lock configuration')
    if abs(get_input('前壳配置','锁深度位移')-1.1)>1e-6:
        raise ValueError('Expected the documented 1.1 lock depth (11 mm offset)')
    rotation,translation,residual=template_transform()
    receipt={'source_sha256':hashlib.sha256(Path(bpy.data.filepath).read_bytes()).hexdigest(),
             'template_rotation':rotation.tolist(),'template_translation_mm':translation.tolist(),
             'base_point_mm':BASE_POINT.tolist(),'feature_fit_residual_mm':residual,
             'pattern_mm':[20,20],'plastic_bore_mm':3.5,'seat_x_mm':SEAT_X,'back_x_mm':BACK_X,'lock_offset_mm':LOCK_OFFSET_MM,
             'lock_tail_relief_diameter_mm':0.0,
             'center_backing_mm':{'thickness':4.0,'length_y':12.0,'width_z':16.0,'center_yz':[4.0,0.0]},
             'latch_image_spec':{'length_mm':40,'width_mm':27,'height_mm':12.5,'plate_thickness_mm':.5,'metal_hole_diameter_mm':3.5},
             'fasteners':{'screws':'8 x M3x10 ISO 7380-1, head D5.7 H1.65','washers':'8 x DIN125 M3, 3.2 x 7 x 0.5 mm','nuts':'8 x DIN985 M3, AF5.5 H4 mm'},
             'mounts':[]}
    created=[]
    def active(obj):
        created.append(obj);transform_template(obj,rotation,translation);return obj
    pads=[active(tube('Reinforcement pad',SEAT_X-.05,BACK_X+.05,5.5,center=(y,z))) for y,z in HOLES]
    # Continuous material between the two front screw pads. No speculative
    # lock-tail aperture: the user requested a solid mounting face here.
    pads.append(active(box('Solid latch centre backing',[SEAT_X,-2,-8],[BACK_X,10,8])))
    cuts=[active(box('Flat 40x27 seat clearance',[-30,-21.8,-13.8],[SEAT_X,18.8,13.8]))]
    for y,z in HOLES:
        cuts.append(active(tube('M3 through hole',-30,40,1.75,center=(y,z))))
        cuts.append(active(tube('Washer and nut rear access',BACK_X,40,4.3,center=(y,z))))
    source=duplicate_local('小锁结构');created.append(source)
    united=solid_boolean([source,*pads],'UNION');created.append(united)
    final=solid_boolean([united,*cuts],'DIFFERENCE');created.append(final)
    original=bpy.data.objects['小锁结构'];original.data=final.data.copy();original.data.name='小锁结构_M3_20x20'
    source_cutter=duplicate_local('小锁布尔');created.append(source_cutter)
    final_cutter=solid_boolean([source_cutter,*cuts],'UNION');created.append(final_cutter)
    bpy.data.objects['小锁布尔'].data=final_cutter.data.copy();bpy.data.objects['小锁布尔'].data.name='小锁布尔_M3_20x20'
    # Remove temporary construction objects before evaluating the final shells.
    for obj in created:
        mesh=obj.data;bpy.data.objects.remove(obj,do_unlink=True)
        if mesh.users==0:bpy.data.meshes.remove(mesh)
    collection=bpy.data.collections.new('Pulsar_Side_Latch_Fasteners_REFERENCE')
    scene.collection.children.link(collection)
    for side,mirror in (('L',1),('R',-1)):
        for index,(y,z) in enumerate(HOLES):
            attached='后壳配置' if y<0 else '前壳配置'
            prefix=f'SideLatch_{side}_{index}'
            pieces=[
                tube(prefix+'_Shaft',5.1,15.1,1.5,center=(y,z),collection=collection),
                tube(prefix+'_Head',3.45,5.1,2.85,center=(y,z),collection=collection),
                tube(prefix+'_Washer',9.6,10.1,3.5,1.6,center=(y,z),collection=collection),
                tube(prefix+'_Nut',10.1,14.1,5.5/math.sqrt(3),1.5,center=(y,z),collection=collection),
            ]
            for obj in pieces:
                v,f=arrays(obj)
                v=v@rotation.T+translation+np.array([LOCK_OFFSET_MM,0,0]);v[:,0]*=mirror;v+=BASE_POINT
                if mirror<0:f=f[:,::-1]
                mesh=bpy.data.meshes.new(obj.name+'_world');mesh.from_pydata(v/1000,[],f);mesh.update();old=obj.data;obj.data=mesh;bpy.data.meshes.remove(old)
                obj['pulsar_print_role']='purchased_hardware_envelope';obj['pulsar_attached_shell']=attached
                obj.color=(.75,.78,.82,1)
            local=np.array([SEAT_X,y,z]);world=local@rotation.T+translation+np.array([LOCK_OFFSET_MM,0,0]);world[0]*=mirror;world+=BASE_POINT
            normal=rotation[:,0].copy();normal[0]*=mirror
            receipt['mounts'].append({'side':side,'index':index,'template_yz_mm':[y,z],'seat_center_world_mm':world.tolist(),'inward_normal':normal.tolist(),'attached_shell':attached,'objects':[o.name for o in pieces]})
    bpy.context.view_layer.update()
    receipt['meshes']={name:evaluated_metrics(name) for name in ('前壳配置','后壳配置')}
    errors=[f'{name}: {error}' for name,metrics in receipt['meshes'].items() for error in failures(metrics)]
    if errors:raise ValueError(errors)
    scene['pulsar_side_latch_revision']=2
    scene['pulsar_side_latch_specification']=json.dumps(receipt,ensure_ascii=False)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.receipt.parent.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output.resolve()))
    receipt['saved_sha256']=hashlib.sha256(args.output.read_bytes()).hexdigest()
    receipt['geometry_passed']=True
    args.receipt.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    print('PASS: 20x20 M3 side-latch candidate saved; assembly checks still required',flush=True)


if __name__=='__main__':main()
