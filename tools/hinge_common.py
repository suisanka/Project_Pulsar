"""Geometry shared by the top-hinge builder and independent assembly checks.

All design dimensions are millimetres; Blender meshes are stored in metres.
Purchased hardware is represented by conservative envelopes, not thread CAD.
"""

import math

import bpy
import numpy as np
from mathutils import Vector


REVISION = 2
AXIS = np.array([-0.010565, 52.80887, 137.9162])
ANCHOR = np.array([-0.010565, 52.881123, 138.17638])
BORE_DIAMETER = 6.6
WORKING_ANGLE = 75.0
CHECKED_ANGLE = 80.0
SHELL_NAMES = ('前壳配置', '后壳配置')
AXLE_NAME = 'Hinge_Axle_D6_L55_M5_REFERENCE'
SPACER_NAME = 'Hinge_Spacer_1p4_PRINT'
HARDWARE_NAMES = (
    AXLE_NAME, 'Hinge_Washer_M6_REFERENCE', SPACER_NAME,
    'Hinge_Washer_M5_REFERENCE', 'Hinge_Nut_M5_REFERENCE',
)
SPEC = {
    'revision': REVISION,
    'axis_world_mm': AXIS.tolist(),
    'axis_direction': [1, 0, 0],
    'opening_rotation': 'rear shell about X, negative degrees',
    'working_angle_deg': WORKING_ANGLE,
    'verification_limit_deg': CHECKED_ANGLE,
    'bore_diameter_mm': BORE_DIAMETER,
    'front_inner_faces_from_axis_mm': [-14.0, 14.0],
    'axle': {
        'quantity': 1, 'example': 'Ganter ISO 7379-6-M5-55',
        'shoulder_diameter_mm': 6.0, 'shoulder_length_mm': 55.0,
        'thread': 'M5 x 0.8', 'thread_length_mm': 9.5,
        'head_diameter_mm': 10.0, 'head_height_mm': 4.5,
        'hex_key_mm': 3.0,
        'shoulder_x_from_axis_mm': [-27.6, 27.4],
        'note': 'Order explicit D6, not the D6.5 ISO-sheet variant. Purchased metal part.',
    },
    'washer_left': {'quantity': 1, 'id_mm': 6.4, 'od_mm': 12.0, 'thickness_mm': 1.6},
    'spacer_right': {'quantity': 1, 'id_mm': 6.6, 'od_mm': 10.0, 'thickness_mm': 1.4},
    'washer_right': {'quantity': 1, 'id_mm': 5.3, 'od_mm': 10.0, 'thickness_mm': 1.0},
    'locknut': {'quantity': 1, 'thread': 'M5 x 0.8', 'standard': 'DIN 985', 'af_mm': 8.0, 'height_mm': 5.0},
    'sources': [
        'https://live-katalog.ganternorm.com/pdf/ganter/EN/7379.pdf',
        'https://www.obo.de/de-de/produkte/unterlegscheibe-12-6-4-1-6-m6-3402061.html',
    ],
}


def mesh_object(name, vertices_mm, faces, collection=None):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(np.asarray(vertices_mm) / 1000, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    (collection or bpy.context.scene.collection).objects.link(obj)
    return obj


def tube(name, x0, x1, radius, inner=0, center=(0, 0), segments=128, collection=None):
    """Closed cylinder / annulus along X, with consistently oriented faces."""
    cy, cz = center
    rings = [(x0, radius), (x1, radius)]
    if inner:
        rings += [(x0, inner), (x1, inner)]
    vertices = [
        (x, cy + r * math.cos(i * 2 * math.pi / segments), cz + r * math.sin(i * 2 * math.pi / segments))
        for x, r in rings for i in range(segments)
    ]
    faces = []
    n = segments
    for i in range(n):
        j = (i + 1) % n
        faces.append((i, j, n + j, n + i))
        if inner:
            faces.extend(((2*n+i, 3*n+i, 3*n+j, 2*n+j), (i, 2*n+i, 2*n+j, j), (n+i, n+j, 3*n+j, 3*n+i)))
    if not inner:
        faces.extend((tuple(reversed(range(n))), tuple(range(n, 2*n))))
    return mesh_object(name, vertices, faces, collection)


def stepped_axle(collection):
    # No thread tessellation: the M5 region is its full major-diameter envelope.
    profile = [(-32.1, 5), (-27.6, 5), (-27.6, 3), (27.4, 3), (27.4, 2.5), (36.9, 2.5)]
    n = 128
    vertices = [(x, r*math.cos(i*2*math.pi/n), r*math.sin(i*2*math.pi/n)) for x,r in profile for i in range(n)]
    faces = [tuple(reversed(range(n))), tuple(range((len(profile)-1)*n, len(profile)*n))]
    for k in range(len(profile)-1):
        for i in range(n):
            j = (i+1) % n
            faces.append((k*n+i, k*n+j, (k+1)*n+j, (k+1)*n+i))
    return mesh_object(AXLE_NAME, vertices, faces, collection)


def hardware(collection):
    objects = [
        stepped_axle(collection),
        tube(HARDWARE_NAMES[1], -27.6, -26.0, 6, 3.2, collection=collection),
        tube(SPACER_NAME, 26.0, 27.4, 5, 3.3, collection=collection),
        tube(HARDWARE_NAMES[3], 27.4, 28.4, 5, 2.65, collection=collection),
        # Circumscribed cylinder contains every orientation of the AF8 hex nut.
        tube(HARDWARE_NAMES[4], 28.4, 33.4, 8/math.sqrt(3), 2.5, collection=collection),
    ]
    for obj in objects:
        obj.location = Vector(AXIS / 1000)
        obj['pulsar_print_role'] = 'print' if obj.name == SPACER_NAME else 'purchased_hardware_envelope'
        obj.color = (.15, .7, .46, 1) if obj.name == SPACER_NAME else (.72, .75, .8, 1)
    return objects


def arrays(name):
    obj = bpy.data.objects[name] if isinstance(name, str) else name
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        mesh.calc_loop_triangles()
        points = np.array([tuple(obj.matrix_world @ v.co) for v in mesh.vertices]) * 1000
        faces = np.array([tuple(t.vertices) for t in mesh.loop_triangles], dtype=np.int32)
        return points, faces
    finally:
        evaluated.to_mesh_clear()


def rotated(points, degrees):
    angle = math.radians(-degrees)
    matrix = np.array([[1, 0, 0], [0, math.cos(angle), -math.sin(angle)], [0, math.sin(angle), math.cos(angle)]])
    return (points - AXIS) @ matrix.T + AXIS
