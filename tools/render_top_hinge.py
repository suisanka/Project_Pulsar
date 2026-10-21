"""Render actual evaluated hinge-v2 geometry, including a 0..75 degree motion strip.

No mesh edits are saved. Hardware threads are conservative envelope models.
"""

import argparse
import json
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Vector

sys.path.insert(0,str(Path(__file__).resolve().parent))
from hinge_common import AXIS, HARDWARE_NAMES, SHELL_NAMES, arrays, mesh_object


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--animation',action='store_true')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:]);args.output.mkdir(parents=True,exist_ok=True)
    side_parts={obj.name:obj['pulsar_attached_shell'] for obj in bpy.data.objects if 'pulsar_attached_shell' in obj}
    side_spec=json.loads(bpy.context.scene['pulsar_side_latch_specification']) if side_parts else None
    side_version='v4' if bpy.context.scene.get('pulsar_side_latch_revision',0)>=2 else 'v3'
    data={name:arrays(name) for name in (*SHELL_NAMES,*HARDWARE_NAMES,*side_parts)}
    scene=bpy.data.scenes.new('Pulsar hinge assembly illustrations');bpy.context.window.scene=scene
    scene.render.engine='BLENDER_WORKBENCH';scene.render.resolution_x=1200;scene.render.resolution_y=900;scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG';scene.view_settings.view_transform='Standard'
    shading=scene.display.shading;shading.light='STUDIO';shading.color_type='OBJECT';shading.show_shadows=False;shading.show_cavity=True;shading.cavity_type='BOTH'
    shading.background_type='WORLD';scene.world=bpy.data.worlds.new('Hinge illustration world');scene.world.color=(.055,.065,.085)
    camera=bpy.data.objects.new('Camera',bpy.data.cameras.new('Camera'));scene.collection.objects.link(camera);scene.camera=camera;camera.data.type='ORTHO'
    copies={}
    details={}
    colors=[(.38,.65,.9,1),(.92,.63,.34,1),(.7,.74,.8,1),(.95,.78,.25,1),(.18,.8,.48,1),(.95,.78,.25,1),(.7,.74,.8,1)]
    for index,(name,(v,f)) in enumerate(data.items()):
        color=colors[index] if index<len(colors) else (.74,.77,.82,1)
        obj=mesh_object(name+'_illustration',v,f);obj.color=color;copies[name]=obj
        if name in SHELL_NAMES:
            selected=(abs(v[:,0])<38)&(v[:,1]>30)&(v[:,1]<82)&(v[:,2]>126)&(v[:,2]<165)
            cropped=f[np.all(selected[f],axis=1)]
            detail=mesh_object(name+'_detail_cutaway',v,cropped)
            detail.color=color;detail.hide_render=True;details[name]=detail
    target=Vector(AXIS/1000)
    def angle(degrees):
        copies[SHELL_NAMES[1]].matrix_world=Matrix.Translation(target)@Matrix.Rotation(-np.deg2rad(degrees),4,'X')@Matrix.Translation(-target)
        details[SHELL_NAMES[1]].matrix_world=copies[SHELL_NAMES[1]].matrix_world
        for name,shell in side_parts.items():
            if shell==SHELL_NAMES[1]:copies[name].matrix_world=copies[SHELL_NAMES[1]].matrix_world
    def detail_mode(enabled):
        for name in SHELL_NAMES:
            copies[name].hide_render=enabled
            details[name].hide_render=not enabled
        for name in side_parts:copies[name].hide_render=enabled
    def render(filename,direction,scale,focus=None):
        at=target if focus is None else Vector(focus)
        camera.location=at+Vector(direction).normalized();camera.rotation_euler=(at-camera.location).to_track_quat('-Z','Y').to_euler();camera.data.ortho_scale=scale
        scene.render.filepath=str(args.output/filename);bpy.ops.render.render(write_still=True)
    # Only detail illustrations use a local face crop for visibility.
    detail_mode(True)
    angle(0);render('hinge-v2-closed.png',(-.5,-.7,-1),.115)
    angle(60);render('hinge-v2-open-detail.png',(-.7,-.7,-1),.13)
    detail_mode(False)
    angle(75);render('hinge-v2-open-75.png',(1,-.2,.1),.64,focus=(0,-.04,.09))
    angle(0)
    # Explode only hardware along its actual assembly axis; shells remain posed.
    detail_mode(True)
    offsets=[-80,-10,13,21,30]
    for name,offset in zip(HARDWARE_NAMES,offsets):copies[name].location.x=offset/1000
    render('hinge-v2-exploded.png',(0,-.8,-.6),.24,focus=(-.024,.053,.138))
    for name in HARDWARE_NAMES:copies[name].location.x=0
    detail_mode(False)
    if args.animation:
        scene.render.resolution_x=800;scene.render.resolution_y=720
        frames=args.output/'motion-frames';frames.mkdir(exist_ok=True)
        for i,degrees in enumerate([*np.linspace(0,75,31),*np.linspace(75,0,31)[1:]]):
            angle(float(degrees));render('motion-frames/frame-%03d.png'%i,(1,-.2,.1),.64,focus=(0,-.04,.09))
    if side_spec:
        angle(0)
        for obj in (*copies.values(),*details.values()):obj.hide_render=True
        for name in SHELL_NAMES:
            v,f=data[name]
            keep=(v[:,0]>-125)&(v[:,0]<-80)&(v[:,1]>-50)&(v[:,1]<20)&(v[:,2]>5)&(v[:,2]<65)
            obj=mesh_object(name+'_side_latch_cutaway',v,f[np.all(keep[f],axis=1)])
            obj.color=copies[name].color
        mounts=[m for m in side_spec['mounts'] if m['side']=='L']
        center=np.array([m['seat_center_world_mm'] for m in mounts]).mean(0)/1000
        normal=np.array(mounts[0]['inward_normal'])
        render(f'side-latch-{side_version}-outside.png',tuple(-normal),.085,focus=center)
        for mount in mounts:
            for name in mount['objects']:copies[name].hide_render=False
        render(f'side-latch-{side_version}-inside.png',tuple(normal+np.array([0,.2,.1])),.085,focus=center+normal*.004)
    print('PASS: assembly illustrations rendered from evaluated meshes',flush=True)


if __name__=='__main__':main()
