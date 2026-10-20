# Project Pulsar：plum 开源头壳模型修复版

本项目是 [@vuicoo](https://github.com/vuicoo) 的开源 Kigurumi 头壳模型 [plumKigurumi-](https://github.com/vuicoo/plumKigurumi-) 的修复版，修复了几何节点和布尔系统中的问题。工程保留参数化前后壳、锁、视孔和眼线结构，支持分别导出 STL，并提供网格与导出回归检查。

具体修改内容见 [Fix_History.md](Fix_History.md)。

日常操作请看 [中文使用手册](docs/USER_GUIDE.zh-CN.md)，包含参数说明、检查视图、STL 导出步骤和常见问题。

## 文件

- `ProjectPulsar_Base.blend`：修复后的工程文件
- `docs/USER_GUIDE.zh-CN.md`：中文使用手册及配图
- `tools/validate_model.py`：在 Blender 中运行的只读几何回归检查
- `tools/repair_model.py`：第五轮修复的可重放脚本，需要明确指定输出文件
- `tools/repair_lock_pin.py`：独立 `r插销` 的清理、保存及 STL 导出脚本

## 使用说明

- 本轮支持并验证的版本为 **Blender 5.2.2 LTS**。其他版本请先运行下方回归检查；历史 5.1.2 的检查结果不能代替当前版本的验证。
- 默认参数使用 Manifold 和拓扑清理。清理后仍存在异常边时，自动启用 **0.1 mm SDF 重建**；这一分支保留参数化能力，但计算更慢、输出面数更多。0.1 mm 是体素尺寸，不是所有位置的最大误差保证。
- 前壳「前后基准值」可调范围是 0～0.85，再往后风扇口会离前后分界线太近。
- 后壳「圆角位置」：0 = 分界线底部没有圆弧缺口，数值越大缺口越大；原作者演示视频的效果约为 0.037。
- 如果视口里出现斜向长条或黑块，请关闭视口着色设置中的 Shadow。这是视口渲染的伪影，不是模型问题。

## 导出 STL

- 前壳（`前壳配置`）和后壳（`后壳配置`）**分别导出**：选中一个，导出时勾选「仅选中项」。两个壳放进同一个 STL，切片软件会把接缝判成非流形边。
- 工程单位是米，导出时把「缩放」设为 **1000**，STL 才是毫米。
- `视孔` 的「生成」「反向」和「瞳距」可继续调整；视孔默认关闭。眼线的布尔、刻字也默认关闭，开启后由 `眼线配置` 导出。
- Base 已隐藏黑色 `睫毛` 和 `眼线配置`，眉形开孔保留；隐藏状态不改变壳体几何。
- 回归检查验证的是数字网格和导出文件，不代替打印材料、支撑、切片、铰链装配和佩戴适配验证。

2026-10-21 的本地交付文件为 `exports/2026-10-21/ProjectPulsar_Front.stl` 和 `ProjectPulsar_Rear.stl`，均为毫米坐标、独立壳体，不包含睫毛、眼线或辅助对象。STL 是可重新生成的本地产物，未纳入 Git；文件哈希、尺寸和检查结果见 [导出清单](docs/stl-export-manifest-2026-10-21.json)。打印方案已确定为 **拓竹 H2S、0.4 mm 喷嘴、PLA**，当前两壳各自可按原尺寸放入其成型空间；[手册的打印优化步骤](docs/USER_GUIDE.zh-CN.md#74-为-3d-打印优化)给出这套设备的候选配置和试打顺序。

锁座和侧边插扣已包含在两份壳体中；独立 `r插销` 另导出为 `exports/2026-10-21/ProjectPulsar_R_Pin.stl`。该零件经清理后为 1,026 个三角面，尺寸约 5.17 × 9.06 × 23.28 mm，详见[锁扣零件说明](docs/USER_GUIDE.zh-CN.md#43-锁扣与独立插销)及[插销验证记录](docs/lock-pin-validation-2026-10-21.json)。插销修复未改变两壳几何；重新打开最新工程导出的三个 STL 均与交付文件的三角形载荷一致。

**闭合机构尚未完成装配验证。** 侧边输出包含锁具安装结构，未包含单独的活动锁具；适配的成品锁型号尚未确认。`r插销` 在原工程中没有装配定位，其配合位置、方向、数量与止退方式均未确认，不能把导出成功理解为“锁扣方案已完整”。顶部铰链孔与侧锁座的局部图及说明见[闭合结构检查](docs/closure-inspection-2026-10-21.json)和手册第 4.3 节。

侧锁的实际安装尺寸和固定方式见[手册第 4.4 节](docs/USER_GUIDE.zh-CN.md#44-侧边搭扣安装尺寸与固定方式)。用户提供的三款商品图中，小号 40 × 27 mm **带锁**、20 × 20 mm 孔距的款式最接近当前结构。模型目前使用实心定位柱，没有螺丝通孔；商品候选与固定方案均尚未完成实物验证。

## 几何回归检查

在仓库根目录运行。以下命令使用 macOS 的 Blender 路径；其他平台需替换可执行文件路径，Windows 还需调整换行方式和 `/tmp` 输出目录：

```sh
"/Applications/Blender.app/Contents/MacOS/Blender" \
  --background --factory-startup --disable-autoexec --python-exit-code 1 \
  ProjectPulsar_Base.blend --python tools/validate_model.py -- \
  --matrix --output /tmp/pulsar-validation.json --exports /tmp/pulsar-stl
```

完整检查包括 45 组锁类型、前后基准值、圆角位置组合，以及默认导出、视孔正反向的三组瞳距、眼线布尔和刻字，再加上三种睫毛在两种睁眼状态下的检查，共 61 个场景。去掉 `--matrix` 可运行 16 个重点场景。检查不会保存或改写工程。

2026-10-21 在 Blender 5.2.2 LTS 上实测 **61/61 通过**。完整记录见 [验证结果](docs/validation-2026-10-21.json)，修复前后精度记录见 [曲面距离检查](docs/surface-comparison-2026-10-21.json)；记录内包含被检文件的 SHA-256。

随后仅调整了睫毛／眼线的隐藏状态，保存后的工程重新打开并通过[当前配置与 STL 检查](docs/print-export-validation-2026-10-21.json)。[隐藏前后对比](docs/print-visibility-verification-2026-10-21.json)确认两壳的顶点和三角面指纹完全一致；两份 STL 的三角形载荷也与 61 场景回归时的默认导出逐字节一致。完整回归记录保留其原始被检 SHA-256。

检查自己保存的参数时，用 `--current` 替换 `--matrix`，并把输入文件换成自己的 `.blend`。此模式不重置参数，要求前后壳的「是否布尔」均已开启；`--exports` 会导出当前前后壳和已开启的视孔／眼线对象。

检查按 STL 的 **float32 毫米坐标**合并重合顶点，再验证开放边、多面共边、面绕序、重复三角形和退化三角形；同时检查工程中的游离边和孤立顶点。面积不大于 `1e-12 mm²` 的三角形视为退化；小于 `1e-8 mm²` 的近零面积三角形另行记录。`--exports` 还会调用 Blender 的真实导出器，重新读取默认和大圆角的四个 STL。

第五轮修复可从 Git 中保存的第四轮版本重放到临时副本：

```sh
git show d26e53d:ProjectPulsar_Base.blend > /tmp/ProjectPulsar_Before.blend
"/Applications/Blender.app/Contents/MacOS/Blender" \
  --background --factory-startup --disable-autoexec --python-exit-code 1 \
  /tmp/ProjectPulsar_Before.blend --python tools/repair_model.py -- \
  --output /tmp/ProjectPulsar_Repaired.blend
```

修复脚本拒绝对已经带有第五轮修复标记的工程重复添加节点。

## 字体

刻字使用的 HarmonyOS Sans SC Bold 已打包进 `.blend`，版权归华为所有，按其字体许可协议使用。

## 许可

原始模型作者：[@vuicoo](https://github.com/vuicoo)（[视频简介](https://twitter.com/i/status/1741975998399439042)）。本修复版与原项目相同，按 **GNU GPL v3** 发布，详见 [LICENSE](LICENSE)。
