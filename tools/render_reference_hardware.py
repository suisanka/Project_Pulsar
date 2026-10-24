"""Render the actual fixed reference-rear assembly and rear-only wire review."""
import argparse
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hinge_common import HARDWARE_NAMES, arrays, mesh_object
from validate_model import fixed_reference_rear


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    if not fixed_reference_rear():
        raise ValueError('Load the reference hardware variant')
    side = [o.name for o in bpy.data.objects if 'pulsar_attached_shell' in o]
    data = {name: arrays(name) for name in ('前壳配置', '后壳配置', *HARDWARE_NAMES, *side)}
    scene = bpy.data.scenes.new('Reference hardware review only')
    bpy.context.window.scene = scene
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.render.resolution_x = scene.render.resolution_y = 1200
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.view_settings.view_transform = 'Standard'
    shading = scene.display.shading
    shading.light, shading.color_type = 'STUDIO', 'OBJECT'
    shading.show_shadows, shading.show_cavity = False, True
    shading.cavity_type, shading.background_type = 'BOTH', 'WORLD'
    scene.world = bpy.data.worlds.new('Reference hardware review background')
    scene.world.color = (.91, .93, .95)
    copies = {}
    for name, mesh in data.items():
        ob = mesh_object(name+'_review', *mesh)
        copies[name] = ob
        ob.color = (.36, .64, .82, 1) if name == '前壳配置' else (.86, .58, .28, 1) if name == '后壳配置' else (.65, .69, .75, 1)
        if name in ('前壳配置', '后壳配置'):
            # Do not average skin normals across a vent wall or bearing edge.
            for selected in bpy.context.selected_objects:
                selected.select_set(False)
            ob.select_set(True)
            bpy.context.view_layer.objects.active = ob
            bpy.ops.object.shade_smooth_by_angle(angle=.6)
    camera = bpy.data.objects.new('ReviewCamera', bpy.data.cameras.new('ReviewCamera'))
    scene.collection.objects.link(camera)
    scene.camera = camera
    camera.data.type, camera.data.ortho_scale = 'ORTHO', .36
    target = Vector((0, -.01, .02))
    args.output.mkdir(parents=True, exist_ok=True)
    def render(label, direction):
        camera.location = target+Vector(direction).normalized()
        camera.rotation_euler = (target-camera.location).to_track_quat('-Z', 'Y').to_euler()
        scene.render.filepath = str(args.output/(label+'.png'))
        bpy.ops.render.render(write_still=True)
    render('assembly-quarter', (1, 1, .3))
    render('assembly-side', (1, 0, 0))
    render('assembly-back', (1, -1, .3))
    for name, ob in copies.items():
        ob.hide_render = name != '后壳配置'
    render('rear-inside', (0, 1, -.05))
    wire = copies['后壳配置'].copy()
    wire.data = wire.data.copy()
    scene.collection.objects.link(wire)
    wire.color = (.01, .02, .025, 1)
    modifier = wire.modifiers.new('Review wire only', 'WIREFRAME')
    modifier.thickness, modifier.offset = .000008, 1
    modifier.use_even_offset = False
    render('rear-wire', (1, -1, .3))
    print('PASS: five actual-geometry review images rendered; blend not saved', flush=True)


if __name__ == '__main__':
    main()
