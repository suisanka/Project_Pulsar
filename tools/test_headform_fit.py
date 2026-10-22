"""Build two dimension-constrained head envelopes and test the closed assembly.

Run in Blender with the unchanged Base loaded. This is a parametric envelope
study, not a reconstruction of a person's unmeasured face, ears or head length.
"""

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hinge_common import HARDWARE_NAMES, SHELL_NAMES, arrays, mesh_object
from validate_model import evaluated_metrics, failures
from validate_top_hinge import inside

HEIGHT, WIDTH, GIRTH, EYE_HEIGHT, IPD = 230., 135., 590., 127., 65.
GIRTH_HEIGHT, CHIN_SHIFT = 157., 45.


def profile(h):
    h = np.asarray(h)
    lower = np.sin(np.clip(h / GIRTH_HEIGHT, 0, 1) * np.pi / 2)
    upper = np.sqrt(np.clip(1 - ((h - GIRTH_HEIGHT) / (HEIGHT - GIRTH_HEIGHT)) ** 2, 0, 1))
    radius = np.where(h < GIRTH_HEIGHT, lower, upper)
    center = CHIN_SHIFT * np.maximum(0, 1 - h / GIRTH_HEIGHT) ** 2
    return radius, center


def ring(exponent, depth, segments=256):
    t = np.arange(segments) * (2 * np.pi / segments)
    return np.column_stack((WIDTH / 2 * np.sign(np.cos(t)) * abs(np.cos(t)) ** (2 / exponent),
                            depth / 2 * np.sign(np.sin(t)) * abs(np.sin(t)) ** (2 / exponent)))


def solve_depth(exponent):
    lo, hi = 100., 350.
    for _ in range(60):
        mid = (lo + hi) / 2
        p = ring(exponent, mid)
        perimeter = np.linalg.norm(np.roll(p, -1, axis=0) - p, axis=1).sum()
        if perimeter < GIRTH:
            lo = mid
        else:
            hi = mid
    return mid


def head_mesh(exponent, depth, segments=256, levels=48):
    # The exact girth plane and extrema are vertices of the generated mesh.
    low = np.linspace(0, GIRTH_HEIGHT, levels + 1)[1:]
    high = GIRTH_HEIGHT + (HEIGHT - GIRTH_HEIGHT) * np.sin(np.linspace(0, np.pi/2, levels+1)[1:-1])
    heights = np.concatenate((low, high))
    base = ring(exponent, depth, segments)
    vertices = [(0., CHIN_SHIFT, 0.)]
    for h in heights:
        radius, center = profile(h)
        vertices.extend((x*radius, y*radius+center, h) for x,y in base)
    top = len(vertices)
    vertices.append((0., 0., HEIGHT))
    faces=[]
    for j in range(segments):
        k=(j+1)%segments
        faces.append((0,1+k,1+j))
        for i in range(len(heights)-1):
            a=1+i*segments+j;b=1+i*segments+k;c=b+segments;d=a+segments
            faces.extend(((a,b,c),(a,c,d)))
        a=1+(len(heights)-1)*segments+j;b=1+(len(heights)-1)*segments+k
        faces.append((a,b,top))
    return np.array(vertices),np.array(faces,dtype=np.int32)


def analytic_inside(points, exponent, depth, offset):
    local=np.asarray(points)-offset
    h=local[:,2]
    radius,center=profile(h)
    safe=np.maximum(radius,1e-10)
    value=(abs(local[:,0])/(WIDTH/2*safe))**exponent+(abs(local[:,1]-center)/(depth/2*safe))**exponent
    return (h>0)&(h<HEIGHT)&(value<1-1e-8)


def pupil_positions(exponent, depth, offset):
    radius,center=profile(EYE_HEIGHT)
    y=depth/2*radius*(1-(IPD/2/(WIDTH/2*radius))**exponent)**(1/exponent)+center
    return np.array([(-IPD/2,y,EYE_HEIGHT),(IPD/2,y,EYE_HEIGHT)])+offset


def widest_run(values):
    runs=[]
    for value in values:
        if not runs or abs(value-runs[-1][-1]-1)>1e-6:runs.append([value])
        else:runs[-1].append(value)
    return max(runs,key=len)


def fit_translation(vertices, obstacle, eye_heights):
    # Directional constraints are only a placement heuristic. Final results use
    # full triangle collision and containment, not this sampled score.
    # Every fourth azimuth and vertical ring keeps the bounded search inexpensive.
    sample=vertices[1:-1].reshape(-1,256,3)[::3,::4].reshape(-1,3)
    candidates=[]
    for eye_z in eye_heights:
        chin_z=eye_z-EYE_HEIGHT
        lo,hi=-60.,60.
        for x,y,h in sample:
            origin=Vector((float(x),0.,float(h+chin_z)))
            front=obstacle.ray_cast(origin,(0,1,0),400)[0]
            rear=obstacle.ray_cast(origin,(0,-1,0),400)[0]
            if front is not None:hi=min(hi,float(front.y)-y)
            if rear is not None:lo=max(lo,float(rear.y)-y)
        candidates.append({"eye_z_mm":eye_z,"y_offset_mm":(lo+hi)/2,
                           "directional_sample_margin_mm":(hi-lo)/2})
    return max(candidates,key=lambda c:c["directional_sample_margin_mm"]),candidates


def setup_scene():
    scene=bpy.data.scenes.new('Pulsar headform fit study')
    bpy.context.window.scene=scene
    scene.unit_settings.system='METRIC';scene.unit_settings.scale_length=1
    scene.render.engine='BLENDER_WORKBENCH'
    scene.render.resolution_x=1200;scene.render.resolution_y=1000;scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG';scene.view_settings.view_transform='Standard'
    shading=scene.display.shading;shading.light='STUDIO';shading.color_type='OBJECT'
    shading.show_shadows=False;shading.show_cavity=True;shading.cavity_type='BOTH'
    shading.background_type='WORLD';scene.world=bpy.data.worlds.new('Headform background');scene.world.color=(.075,.09,.11)
    return scene


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--receipt',type=Path,required=True)
    parser.add_argument('--images',type=Path,required=True)
    parser.add_argument('--qa-scripts',type=Path,required=True)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    source=Path(bpy.data.filepath).resolve();digest=hashlib.sha256(source.read_bytes()).hexdigest()
    if args.output.resolve()==source:raise ValueError('Use a separate study file')
    for path in (args.output.parent,args.receipt.parent,args.images):path.mkdir(parents=True,exist_ok=True)
    side_parts=[o.name for o in bpy.data.objects if 'pulsar_attached_shell' in o]
    names=(*SHELL_NAMES,*HARDWARE_NAMES,*side_parts)
    data={name:arrays(name) for name in names}
    report={'source':source.name,'source_sha256':digest,'blender':bpy.app.version_string,
        'measurements_mm':{'head_height':HEIGHT,'head_width_excluding_ears':WIDTH,'head_circumference':GIRTH,
                           'pupil_height_from_chin':EYE_HEIGHT,'pupil_distance':IPD},
        'confirmed_definitions':'Height and pupil height from lowest chin; width is maximum skull width excluding ears.',
        'assumptions':{'girth_plane_above_chin_mm':GIRTH_HEIGHT,'chin_forward_shift_mm':CHIN_SHIFT,
                       'lower_profile':'sin(pi*h/(2*girth_height)), with a tapered chin',
                       'upper_profile':'elliptical dome','pose':'upright, no pitch/yaw/roll; centered laterally',
                       'head_shapes':'horizontal superellipse exponents 2 and 3, each independently calibrated to all five given dimensions',
                       'not_reconstructed':['nose','ears','hair','neck','individual facial profile'],
                       'excluded':['padding','elastic deformation','entry/removal path','purchased latch covers without CAD','print tolerances']},
        'source_checks':{name:evaluated_metrics(name) for name in SHELL_NAMES},'cases':[]}
    if any(failures(m) for m in report['source_checks'].values()):raise ValueError('Source topology failed')
    trees={name:BVHTree.FromPolygons(v,f,all_triangles=True) for name,(v,f) in data.items()}
    combined_v=[];combined_f=[];count=0
    for v,f in data.values():combined_v.extend(v);combined_f.extend(f+count);count+=len(v)
    combined=BVHTree.FromPolygons(combined_v,combined_f,all_triangles=True)
    front=trees[SHELL_NAMES[0]]
    open_z=[z for z in range(-65,31) if all(front.ray_cast((x,0,z),(0,1,0),200)[0] is None for x in (-IPD/2,IPD/2))]
    run=widest_run(open_z);eye_heights=run[3:-3]
    if not eye_heights:raise ValueError('No common eye opening band with the selected margin')
    report['eye_opening_scan']={'x_mm':[-IPD/2,IPD/2],'step_mm':1,'common_open_z_mm':open_z,
        'selected_band_z_mm':[run[0],run[-1]],'searched_pupil_z_mm':[eye_heights[0],eye_heights[-1]],
        'note':'Straight +Y rays only, not a field-of-view or wearer-visibility acceptance.'}
    print('SOURCE_READY: geometry and pupil opening band evaluated',flush=True)
    scene=setup_scene();assembly=bpy.data.collections.new('Assembly_REFERENCE');scene.collection.children.link(assembly)
    copies={}
    for name,(v,f) in data.items():
        o=mesh_object(name+'_FIT_REFERENCE',v,f,assembly);copies[name]=o
        o.color=(.32,.64,.82,1) if name==SHELL_NAMES[0] else (.86,.58,.28,1) if name==SHELL_NAMES[1] else (.64,.69,.75,1)
        mat=bpy.data.materials.new('M_'+name+'_REFERENCE');mat.diffuse_color=o.color;o.data.materials.append(mat)
    sys.path.insert(0,str(args.qa_scripts));import qa_check;import review_shots
    for exponent,label in ((2,'Ellipse'),(3,'Rounded')):
        depth=solve_depth(exponent);v,f=head_mesh(exponent,depth)
        placement,candidates=fit_translation(v,combined,eye_heights)
        offset=np.array([0.,placement['y_offset_mm'],placement['eye_z_mm']-EYE_HEIGHT])
        collection=bpy.data.collections.new('Headform_'+label);scene.collection.children.link(collection)
        obj=mesh_object('SM_Headform_'+label,v,f,collection);obj.color=(.23,.76,.65,1)
        mat=bpy.data.materials.new('M_Headform_'+label);mat.diffuse_color=obj.color;obj.data.materials.append(mat)
        for poly in obj.data.polygons:poly.use_smooth=True
        bpy.context.view_layer.update()
        qa=qa_check.run(objects=[obj.name],profile='print',uv=False,eps=0.00001)
        if not qa['pass']:raise ValueError(f'Headform QA failed: {qa}')
        # Only our new headform is rendered for topology review.
        review_shots.run(objects=[obj.name],out=str(args.images/f'headform-{label.lower()}-qa-solid.png'),mode='solid',res=360)
        review_shots.run(objects=[obj.name],out=str(args.images/f'headform-{label.lower()}-qa-wire.png'),mode='wire',res=360)
        obj.color=(.23,.76,.65,1)
        obj.location=Vector(offset/1000);bpy.context.view_layer.update()
        world=v+offset;headtree=BVHTree.FromPolygons(world,f,all_triangles=True)
        contacts={};contact_faces=set()
        for name,(ov,of) in data.items():
            intersections=headtree.overlap(trees[name]);pairs=len(intersections)
            contact_faces.update(i for i,_ in intersections)
            enclosed=int(np.count_nonzero(analytic_inside(ov,exponent,depth,offset)))
            head_in_material=inside(trees[name],world[0])
            if pairs or enclosed or head_in_material:
                contacts[name]={'intersecting_triangle_pairs':pairs,'obstacle_vertices_in_analytic_head':enclosed,
                                'head_chin_inside_obstacle_material':head_in_material}
        red=bpy.data.materials.new('M_Intersection_'+label);red.diffuse_color=(.9,.13,.16,1)
        obj.data.materials.append(red)
        for poly in obj.data.polygons:poly.material_index=1 if poly.index in contact_faces else 0
        distances=[combined.find_nearest(Vector(p))[3] for p in world]
        eyes=pupil_positions(exponent,depth,offset)
        rays=[]
        for p in eyes:
            hit=combined.ray_cast(Vector(p),(0,1,0),400)
            rays.append({'origin_xyz_mm':p.tolist(),'blocked':hit[0] is not None,
                         'hit_xyz_mm':list(hit[0]) if hit[0] is not None else None})
        for index,p in enumerate(eyes):
            empty=bpy.data.objects.new(f'Pupil_{label}_{index}',None);collection.objects.link(empty)
            empty.location=Vector(p/1000);empty.empty_display_type='SPHERE';empty.empty_display_size=.003
        obj['head_height_mm']=HEIGHT;obj['head_width_mm']=WIDTH;obj['head_circumference_mm']=GIRTH
        obj['pupil_height_mm']=EYE_HEIGHT;obj['pupil_distance_mm']=IPD;obj['assumed_shape_exponent']=exponent
        obj['fit_result']='INTERSECTION' if contacts else 'NO_INTERSECTION_IN_TESTED_POSE'
        perimeter=float(np.linalg.norm(np.roll(ring(exponent,depth),-1,axis=0)-ring(exponent,depth),axis=1).sum())
        case={'label':label,'exponent':exponent,'implied_head_length_mm':depth,'mesh_vertices':len(v),'mesh_triangles':len(f),
            'measured_height_mm':float(np.ptp(v[:,2])),'measured_width_mm':float(np.ptp(v[:,0])),
            'measured_girth_mm':perimeter,'pupil_distance_mm':float(np.linalg.norm(eyes[1]-eyes[0])),
            'pupil_height_mm':float(eyes[0,2]-world[:,2].min()),'offset_xyz_mm':offset.tolist(),
            'placement':placement,'placement_candidates':candidates,'contacts':contacts,
            'collision_free':not contacts,'sampled_nearest_surface_distance_mm':min(distances),
            'pupil_rays':rays,'qa':qa,
            'side_outline_yz_mm':[], 'girth_outline_xy_mm':[]}
        # Analytic profile sampled densely for the explanatory section diagram.
        h=np.linspace(0,HEIGHT,921);radius,center=profile(h)
        case['side_outline_yz_mm']=np.concatenate((np.column_stack((center+depth/2*radius,h)),
                                                  np.column_stack((center-depth/2*radius,h))[::-1])).__add__(offset[1:]).tolist()
        case['girth_outline_xy_mm']=(ring(exponent,depth)+offset[:2]).tolist()
        case['girth_z_mm']=GIRTH_HEIGHT+offset[2]
        report['cases'].append(case)
        print(f"CASE {label}: depth={depth:.3f} pose={offset.tolist()} collision_objects={list(contacts)} eyes_blocked={[x['blocked'] for x in rays]}",flush=True)
        collection.hide_render=exponent!=2;collection.hide_viewport=exponent!=2
    # Save a dedicated, evaluated study rather than changing parameter controls
    # or reference visibility in the source file.
    for old in list(bpy.data.scenes):
        if old!=scene:bpy.data.scenes.remove(old)
    bpy.data.orphans_purge(do_recursive=True)
    camera=bpy.data.objects.new('HeadFit_Camera',bpy.data.cameras.new('HeadFit_Camera'));scene.collection.objects.link(camera);scene.camera=camera
    camera.data.type='ORTHO';camera.data.ortho_scale=.37
    target=Vector((0,0,.005));camera.location=target+Vector((.8,1,.15));camera.rotation_euler=(target-camera.location).to_track_quat('-Z','Y').to_euler()
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type=='VIEW_3D':
                area.spaces.active.shading.color_type='OBJECT';area.spaces.active.shading.show_xray=True
                area.spaces.active.shading.xray_alpha=.3
                region=area.spaces.active.region_3d;region.view_location=target;region.view_distance=.5
                region.view_rotation=Vector((1,0,0)).to_track_quat('Z','Y');region.view_perspective='ORTHO'
    scene['headform_fit_source_sha256']=digest
    scene.display.shading.color_type='MATERIAL'
    scene['headform_fit_note']='Dimension-constrained envelopes, not a person-specific scan. See JSON report. Toggle Headform_Ellipse / Headform_Rounded collections.'
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output.resolve()),compress=True)
    if hashlib.sha256(source.read_bytes()).hexdigest()!=digest:raise RuntimeError('Source changed')
    report['study_file']=str(args.output);report['study_sha256']=hashlib.sha256(args.output.read_bytes()).hexdigest()
    args.receipt.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('PASS: independent headform study and measurement/collision report saved',flush=True)


if __name__=='__main__':main()
