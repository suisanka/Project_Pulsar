"""Apply the October 2026 topology/vision repair to an unpatched Pulsar project.

Use Blender's --disable-autoexec and --python-exit-code 1. An explicit --output
path is required; no project is overwritten implicitly.
"""

import argparse
import sys
from pathlib import Path

import bpy
from mathutils import Vector


REVISION = 1
VISION_ATTRIBUTE = "pulsar_vision_surface"


def node(group, kind, name, location=(0, 0)):
    item = group.nodes.new(kind)
    item.name = name
    item.label = name
    item.location = location
    item.width = 190
    return item


def compare(group, name, operation, value):
    item = node(group, "FunctionNodeCompare", name)
    item.data_type = "FLOAT"
    item.operation = operation
    item.inputs["B"].default_value = value
    return item


def insert_after(group, source, replacement, input_socket):
    # Multi-input sockets retain previous links when links.new is called.
    # Remove each old link explicitly to avoid intersecting a duplicate operand.
    for link in list(source.links):
        destination = link.to_socket
        group.links.remove(link)
        group.links.new(replacement, destination)
    group.links.new(source, input_socket)


def arrange(group):
    """Lay out generated acyclic groups in dependency columns."""
    ranks = {}

    def rank(item):
        if item.name not in ranks:
            parents = [link.from_node for socket in item.inputs for link in socket.links]
            ranks[item.name] = max((rank(parent) + 1 for parent in parents), default=0)
        return ranks[item.name]

    rows = {}
    for item in group.nodes:
        column = rank(item)
        row = rows.get(column, 0)
        item.location = (column * 240, -row * 230)
        rows[column] = row + 1


def make_cleanup():
    group = bpy.data.node_groups.new("Pulsar 输出拓扑清理", "GeometryNodeTree")
    group.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    group.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    link = group.links.new
    source = node(group, "NodeGroupInput", "输入")
    output = node(group, "NodeGroupOutput", "输出")
    neighbors = node(group, "GeometryNodeInputMeshEdgeNeighbors", "边的相邻面数")
    boundary = compare(group, "开放边", "EQUAL", 1)
    multiple = compare(group, "多面共边", "GREATER_THAN", 2)
    link(neighbors.outputs["Face Count"], boundary.inputs["A"])
    link(neighbors.outputs["Face Count"], multiple.inputs["A"])

    def any_edge_on_face(field, label):
        number = node(group, "ShaderNodeMath", label + "转数值")
        number.operation = "ADD"
        number.inputs[1].default_value = 0
        link(field, number.inputs[0])
        domain = node(group, "GeometryNodeFieldOnDomain", label + "边域")
        domain.data_type = "FLOAT"
        domain.domain = "EDGE"
        link(number.outputs[0], domain.inputs["Value"])
        present = compare(group, label + "所在面", "GREATER_THAN", 0)
        link(domain.outputs[0], present.inputs["A"])
        return present.outputs[0]

    flap = node(group, "FunctionNodeBooleanMath", "同时含开放边和多面共边")
    flap.operation = "AND"
    link(any_edge_on_face(boundary.outputs[0], "开放边"), flap.inputs[0])
    link(any_edge_on_face(multiple.outputs[0], "多面共边"), flap.inputs[1])
    area = node(group, "GeometryNodeInputMeshFaceArea", "面面积")
    bounded = compare(group, "悬挂面小于10平方毫米", "LESS_THAN", 1e-5)
    link(area.outputs[0], bounded.inputs["A"])
    selection = node(group, "FunctionNodeBooleanMath", "仅删除微小悬挂面")
    selection.operation = "AND"
    link(flap.outputs[0], selection.inputs[0])
    link(bounded.outputs[0], selection.inputs[1])
    geometry = source.outputs[0]
    for index in range(8):
        delete = node(group, "GeometryNodeDeleteGeometry", f"剥离悬挂面_{index + 1}")
        delete.domain = "FACE"
        delete.mode = "ALL"
        link(geometry, delete.inputs["Geometry"])
        link(selection.outputs[0], delete.inputs["Selection"])
        geometry = delete.outputs[0]

    island = node(group, "GeometryNodeInputMeshIsland", "连通块")
    total = node(group, "GeometryNodeAccumulateField", "连通块表面积")
    total.data_type = "FLOAT"
    total.domain = "FACE"
    link(area.outputs[0], total.inputs["Value"])
    link(island.outputs["Island Index"], total.inputs["Group ID"])
    count = node(group, "GeometryNodeAccumulateField", "连通块面数")
    count.data_type = "INT"
    count.domain = "FACE"
    count.inputs["Value"].default_value = 1
    link(island.outputs["Island Index"], count.inputs["Group ID"])
    small_area = compare(group, "孤岛面积小于1平方毫米", "LESS_THAN", 1e-6)
    small_count = compare(group, "孤岛面数小于20", "LESS_THAN", 20)
    link(total.outputs["Total"], small_area.inputs["A"])
    link(count.outputs["Total"], small_count.inputs["A"])
    tiny_island = node(group, "FunctionNodeBooleanMath", "微小碎片孤岛")
    tiny_island.operation = "AND"
    link(small_area.outputs[0], tiny_island.inputs[0])
    link(small_count.outputs[0], tiny_island.inputs[1])
    delete = node(group, "GeometryNodeDeleteGeometry", "清除微小碎片孤岛")
    delete.domain = "FACE"
    delete.mode = "ALL"
    link(geometry, delete.inputs["Geometry"])
    link(tiny_island.outputs[0], delete.inputs["Selection"])
    geometry = delete.outputs[0]

    wires = compare(group, "没有相邻面的边", "EQUAL", 0)
    link(neighbors.outputs["Face Count"], wires.inputs["A"])
    delete = node(group, "GeometryNodeDeleteGeometry", "清除游离边")
    delete.domain = "EDGE"
    delete.mode = "ALL"
    link(geometry, delete.inputs["Geometry"])
    link(wires.outputs[0], delete.inputs["Selection"])
    adjacent = node(group, "GeometryNodeInputMeshVertexNeighbors", "顶点邻接")
    loose = compare(group, "没有邻接边的顶点", "EQUAL", 0)
    link(adjacent.outputs["Vertex Count"], loose.inputs["A"])
    vertices = node(group, "GeometryNodeDeleteGeometry", "清除孤立顶点")
    vertices.domain = "POINT"
    vertices.mode = "ALL"
    link(delete.outputs[0], vertices.inputs["Geometry"])
    link(loose.outputs[0], vertices.inputs["Selection"])
    link(vertices.outputs[0], output.inputs[0])
    arrange(group)
    return group


def repair_shell(name, cleanup):
    group = bpy.data.node_groups[name]
    link = group.links.new
    source = group.nodes["清除碎片面_3"].outputs["Geometry"]
    clean = node(group, "GeometryNodeGroup", "输出拓扑清理")
    clean.node_tree = cleanup
    insert_after(group, source, clean.outputs[0], clean.inputs[0])

    # Use the explicitly triangulated surface. Sending the original concave
    # Boolean polygons to SDF would tessellate them again and can fill latch
    # recesses differently. The expensive branch is evaluated lazily.
    sdf = node(group, "GeometryNodeMeshToSDFGrid", "异常输出_SDF_0.1毫米")
    sdf.inputs["Voxel Size"].default_value = 0.0001
    sdf.inputs["Band Width"].default_value = 3
    mesh = node(group, "GeometryNodeGridToMesh", "异常输出_零等值面")
    mesh.inputs["Threshold"].default_value = 0
    mesh.inputs["Adaptivity"].default_value = 0.1
    link(clean.outputs[0], sdf.inputs["Mesh"])
    link(sdf.outputs[0], mesh.inputs["Grid"])
    tri = node(group, "GeometryNodeTriangulate", "重建输出三角化")
    link(mesh.outputs[0], tri.inputs["Mesh"])
    weld = node(group, "GeometryNodeMergeByDistance", "重建输出_连接边1微米")
    weld.inputs["Mode"].default_value = "Connected"
    weld.inputs["Distance"].default_value = 1e-6
    link(tri.outputs[0], weld.inputs["Geometry"])
    rebuilt = node(group, "GeometryNodeGroup", "重建输出拓扑清理")
    rebuilt.node_tree = cleanup
    link(weld.outputs[0], rebuilt.inputs[0])

    neighbors = node(group, "GeometryNodeInputMeshEdgeNeighbors", "输出边面数")
    bad = compare(group, "输出边不是双面", "NOT_EQUAL", 2)
    link(neighbors.outputs["Face Count"], bad.inputs["A"])
    statistic = node(group, "GeometryNodeAttributeStatistic", "输出异常边统计")
    statistic.data_type = "FLOAT"
    statistic.domain = "EDGE"
    link(clean.outputs[0], statistic.inputs["Geometry"])
    link(bad.outputs[0], statistic.inputs["Attribute"])

    # A triangle can have three distinct vertices yet collapse to a line after
    # the world transform and float32 millimetre STL conversion. Evaluate area
    # in that coordinate space without changing the geometry being returned.
    self_object = node(group, "GeometryNodeSelfObject", "导出对象")
    transform = node(group, "GeometryNodeObjectInfo", "导出对象变换")
    transform.transform_space = "ORIGINAL"
    link(self_object.outputs[0], transform.inputs["Object"])
    world = node(group, "GeometryNodeTransform", "导出世界坐标")
    link(clean.outputs[0], world.inputs["Geometry"])
    link(transform.outputs["Location"], world.inputs["Translation"])
    link(transform.outputs["Rotation"], world.inputs["Rotation"])
    link(transform.outputs["Scale"], world.inputs["Scale"])
    millimetres = node(group, "GeometryNodeTransform", "导出毫米坐标")
    millimetres.inputs["Scale"].default_value = (1000, 1000, 1000)
    link(world.outputs[0], millimetres.inputs["Geometry"])
    area = node(group, "GeometryNodeInputMeshFaceArea", "导出三角形面积")
    area_statistic = node(group, "GeometryNodeAttributeStatistic", "导出最小面面积")
    area_statistic.data_type = "FLOAT"
    area_statistic.domain = "FACE"
    link(millimetres.outputs[0], area_statistic.inputs["Geometry"])
    link(area.outputs[0], area_statistic.inputs["Attribute"])
    degenerate = compare(group, "导出面退化", "LESS_EQUAL", 1e-12)
    link(area_statistic.outputs["Min"], degenerate.inputs["A"])
    needs_rebuild = node(group, "FunctionNodeBooleanMath", "非流形或导出退化")
    needs_rebuild.operation = "OR"
    link(statistic.outputs["Max"], needs_rebuild.inputs[0])
    link(degenerate.outputs[0], needs_rebuild.inputs[1])
    switch = node(group, "GeometryNodeSwitch", "仅异常输出启用重建")
    switch.input_type = "GEOMETRY"
    destinations = [
        item.to_socket
        for item in list(clean.outputs[0].links)
        if item.to_node not in (statistic, sdf, world)
    ]
    for destination in destinations:
        link(switch.outputs[0], destination)
    link(needs_rebuild.outputs[0], switch.inputs["Switch"])
    link(clean.outputs[0], switch.inputs["False"])
    link(rebuilt.outputs[0], switch.inputs["True"])
    marker = node(group, "GeometryNodeStoreNamedAttribute", "记录重建状态")
    marker.data_type = "BOOLEAN"
    marker.domain = "POINT"
    marker.inputs["Name"].default_value = "pulsar_output_rebuilt"
    insert_after(group, switch.outputs[0], marker.outputs[0], marker.inputs["Geometry"])
    link(needs_rebuild.outputs[0], marker.inputs["Value"])

    frame = node(group, "NodeFrame", "Pulsar 输出修复")
    frame.label = "Pulsar 输出修复：悬挂面清理 / 异常时 0.1 mm SDF 重建"
    generated = [
        clean, sdf, mesh, tri, weld, rebuilt, neighbors, bad, statistic,
        self_object, transform, world, millimetres, area, area_statistic,
        degenerate, needs_rebuild, switch, marker,
    ]
    for index, item in enumerate(generated):
        item.parent = frame
        item.location = ((index % 4) * 245, -(index // 4) * 280)
    frame.location = group.nodes["清除碎片面_3"].location + Vector((-200, -900))


def repair_vision():
    group = bpy.data.node_groups["视孔"]
    marker = node(group, "GeometryNodeStoreNamedAttribute", "标记头壳来源面")
    marker.data_type = "BOOLEAN"
    marker.domain = "FACE"
    marker.inputs["Name"].default_value = VISION_ATTRIBUTE
    marker.inputs["Value"].default_value = True
    source = group.nodes["物体信息"]
    marker.location = source.location + Vector((230, 0))
    insert_after(group, source.outputs["Geometry"], marker.outputs[0], marker.inputs["Geometry"])
    attribute = group.nodes["已命名属性"]
    attribute.data_type = "BOOLEAN"
    attribute.inputs["Name"].default_value = VISION_ATTRIBUTE
    group.links.new(attribute.outputs["Attribute"], group.nodes["分离几何体"].inputs["Selection"])
    group.nodes.remove(group.nodes["比较"])

    # Preserve the observed default: False selects the inner patch (-Y), True
    # the outer patch (+Y). Island numbering is not stable after Boolean edits.
    normal = node(group, "GeometryNodeInputNormal", "视孔来源面法线")
    separate = node(group, "ShaderNodeSeparateXYZ", "视孔面前后方向")
    inner = compare(group, "视孔内侧面", "LESS_THAN", 0)
    outer = compare(group, "视孔外侧面", "GREATER_THAN", 0)
    group.links.new(normal.outputs[0], separate.inputs[0])
    group.links.new(separate.outputs["Y"], inner.inputs["A"])
    group.links.new(separate.outputs["Y"], outer.inputs["A"])
    group.links.new(inner.outputs[0], group.nodes["切换"].inputs["False"])
    group.links.new(outer.outputs[0], group.nodes["切换"].inputs["True"])
    for name in ("网格孤岛", "比较.003", "比较.004"):
        group.nodes.remove(group.nodes[name])
    normal.location = attribute.location + Vector((0, -250))
    separate.location = normal.location + Vector((220, 0))
    inner.location = separate.location + Vector((220, 100))
    outer.location = separate.location + Vector((220, -160))


def guard_empty_mouth():
    group = bpy.data.node_groups["补洞"]
    fill = group.nodes["群组.001"]
    source = fill.inputs[0].links[0].from_socket
    size = node(group, "GeometryNodeAttributeDomainSize", "嘴部开放边数量")
    size.component = "MESH"
    group.links.new(source, size.inputs["Geometry"])
    valid = compare(group, "嘴部至少三个顶点", "GREATER_THAN", 2)
    group.links.new(size.outputs["Point Count"], valid.inputs["A"])
    switch = node(group, "GeometryNodeSwitch", "闭嘴时跳过填洞")
    switch.input_type = "GEOMETRY"
    insert_after(group, fill.outputs[0], switch.outputs[0], switch.inputs["True"])
    group.links.new(valid.outputs[0], switch.inputs["Switch"])
    size.location = fill.location + Vector((-220, -250))
    valid.location = size.location + Vector((220, 0))
    switch.location = fill.location + Vector((230, 0))


def repair_eyeliner(cleanup):
    group = bpy.data.node_groups["眼线配置"]
    output = next(
        item for item in group.nodes
        if item.bl_idname == "NodeGroupOutput" and item.is_active_output
    )
    source = output.inputs[0].links[0].from_socket
    tri = node(group, "GeometryNodeTriangulate", "眼线输出三角化")
    merge = node(group, "GeometryNodeMergeByDistance", "眼线输出连接边清理")
    merge.inputs["Mode"].default_value = "Connected"
    merge.inputs["Distance"].default_value = 1e-5
    clean = node(group, "GeometryNodeGroup", "眼线输出拓扑清理")
    clean.node_tree = cleanup
    group.links.new(source, tri.inputs[0])
    group.links.new(tri.outputs[0], merge.inputs["Geometry"])
    group.links.new(merge.outputs[0], clean.inputs[0])
    group.links.new(clean.outputs[0], output.inputs[0])
    tri.location = output.location.copy()
    merge.location = tri.location + Vector((230, 0))
    clean.location = merge.location + Vector((230, 0))
    output.location = clean.location + Vector((230, 0))


def configure_parameter_help():
    def socket(group_name, socket_name):
        return next(
            item for item in bpy.data.node_groups[group_name].interface.items_tree
            if item.item_type == "SOCKET"
            and item.in_out == "INPUT"
            and item.name == socket_name
        )

    for group_name, socket_name in (
        ("前壳配置", "锁类型"), ("锁", "锁类型"), ("切换锁类型", "锁类型编号")
    ):
        item = socket(group_name, socket_name)
        item.min_value = 0
        item.max_value = 2
        item.description = "0 = 大锁；1 = 小锁；2 = 无锁。"
    item = socket("睫毛", "睫毛类型")
    item.min_value = 0
    item.max_value = 2
    item.description = "0 = 当前几何数据；1 = 睫毛1；2 = 睫毛2。更换后检查贴合。"
    socket("视孔", "生成").description = "根据头壳来源面生成视孔，无需更改平滑或平直着色。"
    socket("视孔", "反向").description = "关闭时使用头壳内侧面；开启时使用外侧面。"
    socket("视孔", "瞳距").description = "控制左右位置的参数；默认 6.03。生成后核对视线位置。"
    bpy.context.scene["pulsar_parameter_help_revision"] = 1


def repair_eyelash_bindings():
    """Deform each topology before selecting the eyelash style."""
    if bpy.context.scene.get("pulsar_eyelash_bindings_revision"):
        return
    head = bpy.data.objects["头壳"].modifiers["几何节点"]
    face_inputs = {"滑移脸型", "睁眼大小", "腮帮子", "张嘴大小"}
    for item in head.node_group.interface.items_tree:
        if item.item_type == "SOCKET" and item.in_out == "INPUT" and item.name in face_inputs:
            value = getattr(head.properties.inputs, item.identifier).value
            if abs(value) > 1e-7:
                raise RuntimeError("Bind eyelash variants with all four face inputs at zero")
    obj = bpy.data.objects["睫毛"]
    original = obj.modifiers["表面形变"]
    if not original.is_bound:
        raise RuntimeError("The default eyelash deformation must already be bound")
    source_name = "睫毛0_形变源"
    if source_name in bpy.data.objects:
        raise RuntimeError(f"Refusing to overwrite existing object: {source_name}")
    source = obj.copy()
    source.name = source_name
    # Share the base mesh: editing style 0's mesh still updates its deform source.
    obj.users_collection[0].objects.link(source)
    for modifier in list(source.modifiers):
        if modifier.type != "SURFACE_DEFORM":
            source.modifiers.remove(modifier)
    source.hide_set(True)
    source.hide_render = True
    source.hide_select = True

    for name in ("睫毛1", "睫毛2"):
        variant = bpy.data.objects[name]
        deform = variant.modifiers.new("表面形变", "SURFACE_DEFORM")
        deform.target = original.target
        deform.falloff = original.falloff
        deform.strength = original.strength
        variant.modifiers.move(len(variant.modifiers) - 1, 0)
        hidden = variant.hide_get()
        variant.hide_set(False)
        try:
            bpy.context.view_layer.update()
            with bpy.context.temp_override(
                object=variant, active_object=variant,
                selected_objects=[variant], selected_editable_objects=[variant],
            ):
                bpy.ops.object.surfacedeform_bind(modifier=deform.name)
            if not deform.is_bound:
                raise RuntimeError(f"Surface Deform binding failed: {name}")
        finally:
            variant.hide_set(hidden)

    group = bpy.data.node_groups["睫毛"]
    info = node(group, "GeometryNodeObjectInfo", "默认睫毛独立形变")
    info.transform_space = "ORIGINAL"
    info.inputs["Object"].default_value = source
    group.links.new(info.outputs["Geometry"], group.nodes["切换.001"].inputs["True"])
    info.location = group.nodes["切换.001"].location + Vector((-240, 0))
    obj.modifiers.remove(original)
    bpy.context.scene["pulsar_eyelash_bindings_revision"] = 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--parameter-help-only", action="store_true",
        help="Update interface ranges/help on an already repaired project",
    )
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
    if args.parameter_help_only:
        if not bpy.context.scene.get("pulsar_repair_revision"):
            raise RuntimeError("Apply the geometry repair before updating parameter help")
    else:
        if bpy.context.scene.get("pulsar_repair_revision"):
            raise RuntimeError("This project is already patched; refusing to duplicate repair nodes")
        repair_vision()
        cleanup = make_cleanup()
        for name in ("前壳配置", "后壳配置"):
            repair_shell(name, cleanup)
        repair_eyeliner(cleanup)
        guard_empty_mouth()
        repair_eyelash_bindings()
        bpy.context.scene["pulsar_repair_revision"] = REVISION
        bpy.context.scene["pulsar_repair_blender"] = bpy.app.version_string
    configure_parameter_help()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output.resolve()), compress=True)


if __name__ == "__main__":
    main()
