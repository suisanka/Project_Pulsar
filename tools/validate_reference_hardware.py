"""Independent saved-file mesh and interface QA for the rounded rear.

Run mechanical hinge and latch checks separately. No headform is used.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path
import bpy
import numpy as np
from mathutils import Vector
sys.path.insert(0,str(Path(__file__).resolve().parent))
from build_front_thickness import mesh_digest
from build_reference_hardware import BASELINE_SHA,SOURCE_SHA
from copy_reference_rear import native_object,read_native,scene_mm
from hinge_common import AXIS,arrays,mesh_object
from reference_interface_geometry import warp
from repair_side_latches import box
from validate_model import evaluated_metrics,failures,fixed_reference_rear,set_input
from validate_top_hinge import component_seeds,inside,tree

def nearest_errors(points, target, tolerance=.001):
    bvh=tree(*target)
    result=np.array([bvh.find_nearest(p)[3] for p in points])
    # Original STL slivers can make the float BVH overestimate distance.
    triangles=target[0][target[1]].astype(float)
    for i in np.flatnonzero((result>.001)&(result<.05)):
        indices=[hit[2] for hit in bvh.find_nearest_range(points[i],.06)]
        if indices:result[i]=precise_triangle_distance(points[i],triangles[indices])
    return {'samples':len(points),'max_error_mm':float(result.max()) if len(result) else None,
            'over_tolerance':int(np.count_nonzero(result>tolerance)),'tolerance_mm':tolerance}


def proper_intersections(v,f,region):
    bvh=tree(v,f);pairs=[];new=[]
    for a,b in bvh.overlap(bvh):
        if a>=b or set(f[a])&set(f[b]):continue
        pa,pb=v[f[a]],v[f[b]]
        na=np.cross(pa[1]-pa[0],pa[2]-pa[0]);nb=np.cross(pb[1]-pb[0],pb[2]-pb[0])
        la,lb=np.linalg.norm(na),np.linalg.norm(nb)
        if min(la,lb)<1e-12:continue
        da=(pb-pa[0])@(na/la);db=(pa-pb[0])@(nb/lb)
        # Coplanar and point/edge contact are handled by the separate generic
        # coplanar QA; here require actual crossing of both planes by >1 micron.
        if da.min()<-.001 and da.max()>.001 and db.min()<-.001 and db.max()>.001:
            row={'faces':[a,b],'center_mm':np.vstack((pa,pb)).mean(0).tolist()};pairs.append(row)
            if np.any(region[np.r_[f[a],f[b]]]==2):new.append(row)
    return {'proper_crossings':pairs,'crossings_touching_new_transition':new,'plane_tolerance_mm':.001}


def precise_triangle_distance(point, triangles):
    """Double-precision plane/edge distance for slender STL triangles."""
    a, b, c = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    normal = np.cross(b-a, c-a)
    norm2 = np.sum(normal*normal, axis=1)
    valid = norm2 > 1e-30
    denom = np.maximum(norm2, 1e-30)
    offset = np.sum((point-a)*normal, axis=1)
    projection = point-offset[:, None]*normal/denom[:, None]
    barycentric = np.column_stack((
        np.sum(np.cross(b-projection, c-projection)*normal, axis=1)/denom,
        np.sum(np.cross(c-projection, a-projection)*normal, axis=1)/denom,
        np.sum(np.cross(a-projection, b-projection)*normal, axis=1)/denom))
    in_face = valid & np.all(barycentric >= -1e-10, axis=1)
    distances = np.where(in_face, abs(offset)/np.sqrt(denom), np.inf)
    for start, end in ((a, b), (b, c), (c, a)):
        edge = end-start
        fraction = np.clip(np.sum((point-start)*edge, axis=1)/np.maximum(np.sum(edge*edge, axis=1), 1e-30), 0, 1)
        distances = np.minimum(distances, np.linalg.norm(point-start-fraction[:, None]*edge, axis=1))
    return float(distances.min())




def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('build','reference','baseline','qa-scripts','output'):
        parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    build=json.loads(args.build.read_text())
    digest=hashlib.sha256(Path(bpy.data.filepath).read_bytes()).hexdigest()
    if digest!=build['blend_sha256'] or not build.get('passed') or not fixed_reference_rear():
        raise ValueError('Matching build receipt required')
    if hashlib.sha256(args.baseline.read_bytes()).hexdigest()!=BASELINE_SHA:
        raise ValueError('Baseline changed')
    data,sv,sf,_=read_native(args.reference)
    if hashlib.sha256(data).hexdigest()!=SOURCE_SHA:
        raise ValueError('User source changed')
    pose=build['rigid_pose']
    sv=sv.astype(float)@np.array(pose['rotation_matrix']).T+pose['translation_mm']
    v,f=arrays('后壳配置');bvh=tree(v,f)
    actual={name:mesh_digest(arrays(name)) for name in build['unchanged_mesh_digests']}
    front=arrays('前壳配置');front_tree=tree(*front)
    report={'blend_sha256':digest,'source_sha256':SOURCE_SHA,'baseline_sha256':BASELINE_SHA,
            'errors':[],'headform_testing_performed':False,
            'limits':['No physical printing, hardware measurement, torque, fatigue or load test.',
                      'The source posterior contour is resampled and smoothed. Its original triangles and inner wall are not preserved.',
                      'Wall rays are samples, not a mathematical global minimum-thickness proof.']}
    def require(test,message):
        if not test:report['errors'].append(message)
    report['rear_metrics']=evaluated_metrics('后壳配置')
    report['errors']+=failures(report['rear_metrics'])
    report['connected_components']=len(component_seeds(v,f))
    require(report['connected_components']==1,'Rear must be one connected printable part')
    report['self_intersections']=proper_intersections(v,f,np.full(len(v),2))
    require(not report['self_intersections']['proper_crossings'],'Rear contains proper triangle crossings')
    # Independent normal rays on the new body, excluding the intentional neck
    # rim, vent walls and original mechanical band.
    tri=v[f];normal=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]);area2=np.linalg.norm(normal,axis=1)
    normal/=np.maximum(area2[:,None],1e-20);center=tri.mean(1)
    radial=center-[0,-45,30];radial/=np.linalg.norm(radial,axis=1)[:,None]
    ids=np.flatnonzero((warp(center)[:,1]<-27)&(center[:,2]>-75)&(area2>.05)&(np.sum(radial*normal,axis=1)>.8))
    wall_tree=tree(v,f[np.abs(np.sum(radial*normal,axis=1))<.65])
    candidates=len(ids)
    ids=np.array([i for i in ids if wall_tree.find_nearest(center[i])[3]>3.5],dtype=int)
    ids=ids[::max(1,int(np.ceil(len(ids)/3000)))];wall=[];missing=[]
    for i in ids:
        hit,n,_,distance=bvh.ray_cast(Vector(center[i]-.001*normal[i]),Vector(-normal[i]),12)
        if hit is None:missing.append(center[i].tolist())
        else:wall.append({'outer_mm':center[i].tolist(),'thickness_mm':distance+.001,'exit_normal_dot':float(np.dot(n,-normal[i]))})
    thickness=np.array([row['thickness_mm'] for row in wall])
    report['body_wall']={'selection':'Outer body faces, at least 3.5 mm from a vent side wall or rim; mechanical band and neck excluded','candidate_faces':candidates,'samples':len(ids),'missing':missing,'min_mm':float(thickness.min()) if len(thickness) else None,
                         'percentiles_01_50_99_mm':np.quantile(thickness,[.01,.5,.99]).tolist() if len(thickness) else [],'rays':wall}
    require(len(ids)>1000 and not missing and len(thickness)>0 and thickness.min()>2,'New body has missing or <2 mm wall samples')
    # Reference comparison is reported honestly as a smoothed outer contour,
    # not as byte-identical adoption of the old STL.
    p=sv[sf];n=np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0]);n/=np.linalg.norm(n,axis=1)[:,None];c=p.mean(1)
    radial=c-[0,-45,30];radial/=np.linalg.norm(radial,axis=1)[:,None]
    samples=c[(warp(c)[:,1]<-40)&(c[:,2]>-75)&(np.sum(n*radial,axis=1)>.8)][::5]
    # Compare the continuous contour guide, not a hole edge when a source
    # sample lands inside the newly cut aperture. Report final-surface distance
    # separately so the two measurements cannot be confused.
    guide=bpy.data.objects[build['construction']['outer_skin_object']]
    for collection in guide.users_collection:collection.hide_viewport=False
    guide.hide_set(False)
    bpy.context.view_layer.update()
    guide_tree=tree(*arrays(guide))
    errors=np.array([guide_tree.find_nearest(point)[3] for point in samples])
    final_errors=np.array([bvh.find_nearest(point)[3] for point in samples])
    # The collar guide changes the contour close to the mating edge. Keep that
    # displacement visible in the full result, and apply the preservation bound
    # to the posterior body beyond the interface-adjacent band.
    posterior=warp(samples)[:,1]<-50
    report['reference_outer_contour']={'samples':len(samples),'max_nearest_error_mm':float(errors.max()),
                                      'method':'Source exterior samples to continuous generated skin before perforation',
                                      'p50_p95_p99_error_mm':np.quantile(errors,[.5,.95,.99]).tolist(),
                                      'perforated_final_max_nearest_error_mm':float(final_errors.max()),
                                      'posterior_body_q_max':-50,
                                      'posterior_body_samples':int(posterior.sum()),
                                      'posterior_body_max_error_mm':float(errors[posterior].max()),
                                      'interface_adjacent_max_error_mm':float(errors[~posterior].max()),
                                      'limit':'The full comparison includes the deliberately rounded transition to the original collar; it is not an exact copy of the supplied STL.'}
    require(posterior.sum()>1000 and errors[posterior].max()<2,'Posterior body exceeds 2 mm resampling envelope')
    report['removed_lower_tabs']=[]
    source_tree=tree(sv,sf)
    for side in (-1,1):
        lo=np.array([75,-23.5,-52.]);hi=np.array([110,-11.5,-22.])
        if side<0:lo[0],hi[0]=-hi[0],-lo[0]
        test=tree(*arrays(box('Removed tab negative control',lo,hi)))
        new_pairs=len(bvh.overlap(test));old_pairs=len(source_tree.overlap(test))
        samples=np.array([(x,y,z) for x in np.linspace(lo[0],hi[0],4) for y in np.linspace(lo[1],hi[1],4) for z in np.linspace(lo[2],hi[2],4)])
        occupied=sum(inside(bvh,p) for p in samples)
        report['removed_lower_tabs'].append({'side':side,'bounds_mm':[lo.tolist(),hi.tolist()],'source_surface_pairs':old_pairs,'result_surface_pairs':new_pairs,'occupied_samples':occupied})
        require(old_pairs>0 and new_pairs==0 and occupied==0,'Marked obsolete lower tab remains')
    # Verify actual rear mating points against original geometry, including the
    # centre barrel and the protected bore/seat cores, rather than a marker.
    mating=(warp(v)[:,1]>-8)&(v[:,2]>-83.9)&np.array([front_tree.find_nearest(p)[3]<2 for p in v])
    relative=v-AXIS
    hinge=(abs(relative[:,0])<13.4)&(np.linalg.norm(relative[:,1:],axis=1)<6.8)
    spec=json.loads(bpy.context.scene['pulsar_side_latch_specification'])
    masks={'mating_edge':mating,'hinge_barrel':hinge}
    for row in spec['mounts']:
        if row['index'] not in (0,1):continue
        offset=v-np.array(row['seat_center_world_mm']);n=np.array(row['inward_normal']);depth=offset@n
        radius=np.linalg.norm(offset-depth[:,None]*n,axis=1)
        masks[row['side']+str(row['index'])]=(depth>-.01)&(depth<4.01)&(radius<3.1)
    sys.path.insert(0,str(args.qa_scripts.resolve()));import qa_check
    scene=scene_mm('Independent rear mesh QA');bpy.context.window.scene=scene;obj=native_object('Rear_mm',v,f,scene)
    mat=bpy.data.materials.new('QA');obj.data.materials.append(mat)
    report['generic_qa']=qa_check.run(objects=[obj.name],profile='print',uv=False,eps=1e-5,tol=.001,max_tris=len(f)+1)
    require(report['generic_qa']['pass'],'Generic print mesh QA failed')
    bpy.ops.wm.open_mainfile(filepath=str(args.baseline.resolve()),load_ui=False)
    baseline={name:mesh_digest(arrays(name)) for name in actual}
    report['unchanged_front_and_hardware']=actual==baseline==build['unchanged_mesh_digests']
    report['compared_objects']=len(actual)
    require(report['unchanged_front_and_hardware'],'Front or original hardware changed')
    empty=mesh_object('Baseline without decorative rear vents',[],[])
    set_input('后壳配置','后壳打洞',empty);bpy.context.view_layer.update();old_rear=arrays('后壳配置')
    report['original_interfaces']={name:nearest_errors(v[mask],old_rear,.002) for name,mask in masks.items()}
    for name,row in report['original_interfaces'].items():
        require(row['samples']>0 and row['over_tolerance']==0,'Original interface changed: '+name)
    report['passed']=not report['errors']
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('QUALITY',report['passed'],report['errors'],'WALL',report['body_wall']['min_mm'],'SOURCE',report['reference_outer_contour'],flush=True)
    if report['errors']:raise RuntimeError(report['errors'])


if __name__=='__main__':
    main()
