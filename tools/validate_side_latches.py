"""Validate eight real side-latch bores, bearing pads and fastener clearance."""

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

sys.path.insert(0,str(Path(__file__).resolve().parent))
from hinge_common import arrays
from validate_model import evaluated_metrics, failures
from validate_top_hinge import tree, inside


def hits_along(bvh, origin, direction, limit):
    direction=Vector(direction).normalized();start=Vector(origin);point=start.copy();hits=[]
    for _ in range(30):
        location,_,_,distance=bvh.ray_cast(point,direction,limit)
        if location is None:break
        travel=(location-start).dot(direction)
        if travel>limit:break
        hits.append(travel);point=location+direction*.0001
    return hits


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    spec=json.loads(bpy.context.scene['pulsar_side_latch_specification'])
    report={'blend_sha256':hashlib.sha256(Path(bpy.data.filepath).read_bytes()).hexdigest(),'mounts':[],'errors':[],
            'limits':['Purchased latch outline/hole pattern follows the user drawing; moving cover internals and actual lock-cylinder tail dimensions are not supplied.','No physical printing, screw torque or fatigue test.']}
    shells={name:arrays(name) for name in ('前壳配置','后壳配置')};trees={name:tree(*mesh) for name,mesh in shells.items()}
    def require(value,message):
        if not value:report['errors'].append(message)
    for mount in spec['mounts']:
        center=np.array(mount['seat_center_world_mm']);normal=np.array(mount['inward_normal']);bvh=trees[mount['attached_shell']]
        u=np.cross(normal,[0,0,1]);u/=np.linalg.norm(u);v=np.cross(normal,u)
        midpoint=center+2*normal;radii=[];wall=[]
        for angle in np.linspace(0,2*math.pi,64,endpoint=False):
            direction=u*math.cos(angle)+v*math.sin(angle)
            hit,_,_,distance=bvh.ray_cast(Vector(midpoint),Vector(direction),6)
            if hit is None:
                report['errors'].append(f'{mount["side"]}{mount["index"]}: missing bore wall')
            else:
                radii.append(distance);wall.append(np.array(hit))
        through=hits_along(bvh,center-10*normal,normal,30)
        require(not through,f'{mount["side"]}{mount["index"]}: hole does not pass through')
        require(len(radii)==64 and min(radii)>1.72 and max(radii)<1.78,f'{mount["side"]}{mount["index"]}: D3.5 bore mismatch')
        thickness=[]
        for angle in np.linspace(0,2*math.pi,16,endpoint=False):
            radial=2.5*(u*math.cos(angle)+v*math.sin(angle))
            hits=hits_along(bvh,center+radial-2*normal,normal,10)
            if len(hits)!=2:
                report['errors'].append(f'{mount["side"]}{mount["index"]}: non-solid bearing pad {hits}')
            else:thickness.append(hits[1]-hits[0])
        require(len(thickness)==16 and min(thickness)>3.95 and max(thickness)<4.05,f'{mount["side"]}{mount["index"]}: bearing pad not 4 mm')
        # Fit the actual bore section to recover its centre, rather than copying
        # the design coordinates into the hole-pitch result.
        wall=np.array(wall);q=np.column_stack(((wall-midpoint)@u,(wall-midpoint)@v))
        coeff=np.linalg.lstsq(np.column_stack((2*q,np.ones(len(q)))),np.sum(q*q,axis=1),rcond=None)[0]
        measured_center=midpoint+coeff[0]*u+coeff[1]*v-2*normal
        for name in mount['objects']:
            metrics=evaluated_metrics(name);require(not failures(metrics),f'{name}: invalid hardware envelope')
            if name.endswith(('_Shaft','_Head')):
                points,faces=arrays(name);overlap=len(trees[mount['attached_shell']].overlap(tree(points,faces)))
                contained=inside(trees[mount['attached_shell']],points[0])
                require(not overlap and not contained,f'{name}: collides with its mounting shell')
        row={**mount,'measured_center_world_mm':measured_center.tolist(),'min_bore_radius_mm':min(radii),'max_bore_radius_mm':max(radii),
             'min_pad_thickness_mm':min(thickness) if thickness else None,'max_pad_thickness_mm':max(thickness) if thickness else None,
             'nominal_thread_past_nut_mm':10-.5-4-.5-4}
        report['mounts'].append(row)
        print('MOUNT',mount['side'],mount['index'],'bore',min(radii),max(radii),'pad',thickness,flush=True)
    report['patterns']=[]
    for side in ('L','R'):
        c={m['index']:np.array(m['measured_center_world_mm']) for m in report['mounts'] if m['side']==side}
        dimensions=[float(np.linalg.norm(c[a]-c[b])) for a,b in ((0,1),(2,3),(0,2),(1,3))]
        require(all(abs(d-20)<.002 for d in dimensions),side+' hole pitch is not 20 x 20 mm')
        report['patterns'].append({'side':side,'measured_edge_lengths_mm':dimensions})
    report['passed']=not report['errors'];args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    if report['errors']:raise RuntimeError(report['errors'])
    print('PASS: eight through holes, both 20x20 patterns, 4 mm pads and M3 fasteners checked',flush=True)


if __name__=='__main__':main()
