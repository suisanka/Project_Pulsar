# Project Pulsar：plum 开源头壳模型修复版

本项目是 [@vuicoo](https://github.com/vuicoo) 的开源 Kigurumi 头壳模型 [plumKigurumi-](https://github.com/vuicoo/plumKigurumi-) 的修复版，修复了几何节点和布尔系统中的问题。工程保留参数化前后壳、锁、视孔和眼线结构，支持分别导出 STL，并提供网格与导出回归检查。

具体修改内容见 [Fix_History.md](Fix_History.md)。

日常操作请看 [中文使用手册](docs/USER_GUIDE.zh-CN.md)，包含参数说明、检查视图、STL 导出步骤和常见问题。

**2026-10-24 当前适配方案：** 根据最新要求，以用户后壳轮廓重建连续圆润曲面，沿用原版对接分缝、铰链和锁扣安装位，删除下方两处废弃凸块；搭配现有 Front3mm 前脸。没有使用头模。独立工程与打印文件见[圆润后壳版本说明](docs/REFERENCE_REAR_ROUNDED.zh-CN.md)。`dbc034d` 对应的[后壳原样采用版本](docs/REFERENCE_REAR_EXACT.zh-CN.md)及输入 STL 保持不变，作为来源基准。

## 文件

- `ProjectPulsar_Base.blend`：修复后的工程文件
- `docs/USER_GUIDE.zh-CN.md`：中文使用手册及配图
- `tools/validate_model.py`：在 Blender 中运行的只读几何回归检查
- `tools/repair_model.py`：第五轮修复的可重放脚本，需要明确指定输出文件
- `tools/repair_lock_pin.py`：旧 `r插销` 的历史清理脚本；当前装配不使用该件
- `tools/repair_top_hinge.py`、`tools/repair_side_latches.py`：肩轴铰链和侧锁螺丝安装座的可重放改造
- `tools/validate_top_hinge.py`、`tools/validate_side_latches.py`：装配运动、孔距、通孔和承压厚度检查
- `tools/export_top_hinge.py`：要求同一工程的装配验证通过后，导出七个打印 STL
- `tools/render_top_hinge.py`：从实际求值网格生成装配示意与开合动画

## 使用说明

- 本轮支持并验证的版本为 **Blender 5.2.2 LTS**。其他版本请先运行下方回归检查；历史 5.1.2 的检查结果不能代替当前版本的验证。
- 默认参数使用 Manifold 和拓扑清理。清理后仍存在异常边时，自动启用 **0.1 mm SDF 重建**；这一分支保留参数化能力，但计算更慢、输出面数更多。0.1 mm 是体素尺寸，不是所有位置的最大误差保证。
- 前壳「前后基准值」可调范围是 0～0.85，再往后风扇口会离前后分界线太近。
- 后壳「圆角位置」：0 = 分界线底部没有圆弧缺口，数值越大缺口越大；原作者演示视频的效果约为 0.037。
- 如果视口里出现斜向长条或黑块，请关闭视口着色设置中的 Shadow。这是视口渲染的伪影，不是模型问题。

## 导出 STL

**2026-10-22 前脸 3 mm 版本：** 前壳主体的 Solidify 名义厚度从 2.62 mm 改为 3 mm，后壳、耳部和机械定位基准保持原版。独立工程为 `variants/front-3mm/ProjectPulsar_Front3mm.blend`，打印文件位于 `exports/2026-10-22-front-3mm/`。曲面处理后五处法线壁厚抽测为 2.75–2.94 mm，**不代表全域最小壁厚 3 mm**。详见[版本说明、下载路径与验证记录](docs/FRONT_3MM.zh-CN.md)。下方 v4 说明及原始 Base 仍对应原厚度。

- 前壳（`前壳配置`）和后壳（`后壳配置`）**分别导出**：选中一个，导出时勾选「仅选中项」。两个壳放进同一个 STL，切片软件会把接缝判成非流形边。
- 工程单位是米，导出时把「缩放」设为 **1000**，STL 才是毫米。
- `视孔` 的「生成」「反向」和「瞳距」可继续调整；视孔默认关闭。眼线的布尔、刻字也默认关闭，开启后由 `眼线配置` 导出。
- Base 已隐藏黑色 `睫毛` 和 `眼线配置`，眉形开孔保留；隐藏状态不改变壳体几何。
- 回归检查验证的是数字网格和导出文件，不代替打印材料、支撑、切片、铰链装配和佩戴适配验证。

原版 Closure v4 打印文件在 **`exports/2026-10-21-closure-v4/`**；本次圆润后壳使用 `exports/2026-10-24-reference-rear-rounded/`。以下为原版文件名：

- `ProjectPulsar_Front_Closure_v4.stl`、`ProjectPulsar_Rear_Closure_v4.stl`：整套前后壳，各一件。
- `ProjectPulsar_Hinge_Spacer_1p4.stl`：顶部轴向垫套，一件，已平放。
- `ProjectPulsar_Hinge_Test_Front.stl`、`ProjectPulsar_Hinge_Test_Rear.stl`：顶部局部试打件。
- `ProjectPulsar_SideLatch_Test_Front_L.stl`、`ProjectPulsar_SideLatch_Test_Rear_L.stl`：侧锁局部试打件。

STL 单位为毫米，按仓库惯例保留为本地产物，未纳入 Git；源工程、重放／验证／导出脚本和[文件哈希清单](docs/top-hinge-stl-manifest-2026-10-21.json)纳入版本管理。旧 `exports/2026-10-21/`、`exports/2026-10-21-hinge-v2/` 和 `exports/2026-10-21-closure-v3/` 不与本版混用。

顶部使用 **Ø6 × 55 mm 光轴、M5 尾牙的金属肩轴螺钉**，配两种金属平垫圈、1.4 mm 打印垫套和 M5 防松螺母。前后轴孔 Ø6.6 mm，每侧耳轴间隙约 0.728 mm，止退后的轴向余量约 1.02 mm。旧 `r插销` 隐藏并标为历史件，本版不装配。左侧轴头插入通道已让位；移除了阻碍起始开合的刚性侧插舌。

两侧改为 **40 × 27 × 12.5 mm 带锁搭扣、20 × 20 mm 孔距**的 M3 穿孔固定。每侧 4 孔，共 8 孔，孔径 Ø3.5 mm，承压厚度 4 mm；背面留出垫圈、防松螺母和套筒空间。两侧中心已取消 Ø10 mm 让位孔，改为 12 × 16 mm、厚 4 mm 的实体连接区。使用 8 套 M3 × 10 低圆头螺丝、M3 平垫圈及 M3 防松螺母。完整采购／打印数量、规格、安装顺序见[中文使用手册](docs/USER_GUIDE.zh-CN.md)第 4.3～4.5 节，STL 复现命令见第 7.5 节。

默认配置已完成 **0–80°、每 0.25° 共 321 个姿态**的两壳与顶部／侧锁五金包络检查，常用开角为 **0–75°**。另验证轴向装入、工具通道、止退对照、8 个侧锁通孔、两组实测孔距和承压厚度。记录见[开合装配验证](docs/top-hinge-validation-2026-10-21.json)与[侧锁验证](docs/side-latch-validation-2026-10-21.json)。这些是数字几何检查；没有实际打印、五金到货测量、扭矩、疲劳或承载试验，商品搭扣活动盖也没有完整 CAD 数据。先用随附局部试打件和实物五金确认，再打印整壳。

打印方案为 **拓竹 H2S、0.4 mm 喷嘴、PLA**。两壳各自保持 100% 尺寸可放入名义成型空间；手册给出候选切片配置，本次没有生成 G-code。

## 头壳剖面

[垂直剖面主图](docs/images/head-vertical-section.png)沿模型正中线 `X = 0 mm` 从面部到后脑切开，展示额头、鼻部、下巴、后脑与顶部连接处的实际轮廓。图中面部朝右，附俯视定位图；可放大的原始轮廓见[正中矢状剖面 SVG](docs/images/head-section-sagittal-x0mm.svg)。

[净空与壁厚标注图](docs/images/head-vertical-section-dimensioned.png)及[标注版 SVG](docs/images/head-vertical-section-dimensioned.svg)进一步标出实际测量端点。`Z = +80 / 0 / -60 mm` 处的前后净深分别为 **217.8 / 212.2 / 207.9 mm**；`Y = +80 mm` 处从下巴内侧至顶部连接座下表面的竖直净高为 **246.3 mm**。下方颈口开放，该净高只在标注竖线上成立。

沿八个外表面取样点的三角面法线向内测得：顶部 **2.55 mm**、上后脑 **2.55 mm**、下后脑 **2.57 mm**、额头 **2.57 mm**、眉鼻间 **2.57 mm**、鼻尖 **2.23 mm**、口部 **2.38 mm**、下巴底部 **2.49 mm**。这些是局部法线射线壁厚，不代表全壳最小值或统一壁厚；两位小数为数值读数精度，不是制造公差。净空未扣除独立五金、内衬和打印偏差。测量端点、法线、源文件哈希、拓扑与射线复核结果见[尺寸记录](docs/head-vertical-section-dimensions-2026-10-22.json)。

[水平横切面主图](docs/images/head-horizontal-section.png)展示模型原始坐标 `Z = 0 mm` 的截面，附中线侧剖面定位；[三高度对照图](docs/images/head-horizontal-sections-comparison.png)展示 `Z = -40 / 0 / +60 mm`。从头顶向下看，面部朝上，蓝色为前壳，橙色为后壳，网格间距 20 mm。

截面直接取自当前 Base 求值后的三角网格，色块对应被平面切到的实体材料，仅含前后壳，不含独立五金、内衬或佩戴者。水平 `Z = 0 mm` 截面外包络为 **252.1 × 217.5 mm**，包含此高度的耳部；这不是内部净空尺寸。Z 使用模型坐标，不能直接理解为从下巴起算的高度。可放大的原始轮廓见 [Z = 0 SVG](docs/images/head-section-z+0mm.svg)，源文件哈希、拓扑检查及轮廓数据见[剖面记录](docs/head-cross-sections-2026-10-22.json)。

复现时先用 Blender 提取几何，再用安装了 Pillow 的 Python 绘图；`--font` 可指定支持中文的字体，默认使用 macOS 的黑体。脚本不保存或改写 `.blend`：

```sh
"/Applications/Blender.app/Contents/MacOS/Blender" \
  --background --factory-startup --disable-autoexec --python-exit-code 1 \
  ProjectPulsar_Base.blend --python tools/render_cross_sections.py -- \
  --output /tmp/pulsar-sections.json
python3 tools/render_cross_sections.py --draw /tmp/pulsar-sections.json --output docs/images
```

复现尺寸标注（使用上一步匹配同一源模型的截面数据）：

```sh
"/Applications/Blender.app/Contents/MacOS/Blender" \
  --background --factory-startup --disable-autoexec --python-exit-code 1 \
  ProjectPulsar_Base.blend --python tools/dimension_vertical_section.py -- \
  --sections /tmp/pulsar-sections.json --output /tmp/pulsar-dimensions.json
python3 tools/dimension_vertical_section.py --sections /tmp/pulsar-sections.json \
  --draw /tmp/pulsar-dimensions.json --output docs/images
```

## 指定尺寸的头模适配测试

已按 **头高 230 mm、最大头宽 135 mm（不含耳）、头围 590 mm、瞳高 127 mm、瞳距 65 mm** 建立两个独立的参数包络头模。头高、瞳高均从下巴最低点起算，量法已确认。测试工程为 [ProjectPulsar_HeadformFit_230-135-590.blend](studies/headform-fit-2026-10-22/ProjectPulsar_HeadformFit_230-135-590.blend)，原始 Base 未修改。

头长和真实轮廓尚未提供，因此用两种满足相同输入尺寸的截面作假设对照。两者都使用假设的下巴收窄轮廓，头围平面位于下巴以上 157 mm；鼻、耳、头发及个体脸型没有重建。这是尺寸包络测试，不能视为真人扫描或最终佩戴结论。

| 假设头模 | 根据头宽／头围推算的头长 | 测试姿态的完整三维结果 | 瞳距 65 mm 的左右直视线 |
|---|---:|---|---|
| 椭圆水平截面，指数 2 | 233.95 mm | 与前壳、后壳相交 | 均通过现有眼部开口 |
| 方圆水平截面，超椭圆指数 3 | 212.26 mm | 与前壳、后壳相交，干涉较小 | 均通过现有眼部开口 |

姿态搜索保持头模竖直、左右居中，在两眼共同通光高度中保留 3 mm 的采样余量后搜索上下与前后平移，没有扫描俯仰、偏航或侧倾，也没有验证戴入／取下路径。最终所选瞳孔高度分别为模型坐标 `Z = -11 / -15 mm`。所有已建模的顶部连接件和侧锁紧固件均纳入碰撞检查，未检出与这些部件相交；尚无 CAD 的商品搭扣活动盖不在检查范围内。

见[三维剖视对照图](docs/images/headform-fit-comparison.png)和[正中剖面叠合图](docs/images/headform-fit-sections.png)。绿色表示尺寸包络，红色标出与完整装配相交的头模三角面。Blender 工程中默认显示 `Headform_Ellipse`；可切换到 `Headform_Rounded`，不要同时显示两个候选头模作为同一次试戴。

两个头模均为 **48,640 个三角面**，通过独立网格 QA。另存工程重读后，头高、头宽、头围、碰撞数量均复核通过。完整假设、放置搜索、测量、眼位射线和碰撞记录见[测试记录](docs/headform-fit-2026-10-22.json)，重读结果见[保存验证](docs/headform-fit-readback-2026-10-22.json)。前后向搜索余量是定向采样指标，不能解释为法线穿透深度；相交姿态的最近表面距离也不能解释为可用净空。

下一步最有用的实测数据是**额头到后脑的最大直线头长**及正侧面轮廓。当前结果不支持直接认定真人适配，也不支持据此统一缩放带有固定孔径和装配公差的壳体。内衬、打印偏差和软组织变形未计入。

复现脚本：`tools/test_headform_fit.py` 在加载 Base 的 Blender 中运行，要求 `--output` 指向独立 `.blend`、`--receipt` 指向 JSON、`--images` 指向 QA 图片目录，`--qa-scripts` 指向 `blender-asset-qa/scripts`；随后用 `tools/render_headform_fit.py` 重读测试工程、检查并渲染，用安装 Pillow 的 Python 运行 `tools/illustrate_headform_fit.py` 组合对照图。各脚本的 `--help` 列出参数。

## 几何回归检查

在仓库根目录运行。以下命令使用 macOS 的 Blender 路径；其他平台需替换可执行文件路径，Windows 还需调整换行方式和 `/tmp` 输出目录：

```sh
"/Applications/Blender.app/Contents/MacOS/Blender" \
  --background --factory-startup --disable-autoexec --python-exit-code 1 \
  ProjectPulsar_Base.blend --python tools/validate_model.py -- \
  --matrix --output /tmp/pulsar-validation.json --exports /tmp/pulsar-stl
```

完整检查包括 45 组锁类型、前后基准值、圆角位置组合，以及默认导出、视孔正反向的三组瞳距、眼线布尔和刻字，再加上三种睫毛在两种睁眼状态下的检查，共 61 个场景。去掉 `--matrix` 可运行 16 个重点场景。检查不会保存或改写工程。

原版 Closure v4 合并改造后在 Blender 5.2.2 LTS 上实测 **61/61 通过**，结果见[原版回归记录](docs/top-hinge-regression-2026-10-21.json)，内含当前源工程 SHA-256。默认配置另有前述机械装配检查；参数矩阵中的其他配置只接受拓扑与导出检查，未逐一进行运动学验收。修改头型、分界、锁深度等参数后需要重新核对机械装配。

[第五轮验证](docs/validation-2026-10-21.json)、[曲面距离检查](docs/surface-comparison-2026-10-21.json)、[旧隐藏状态检查](docs/print-visibility-verification-2026-10-21.json)等仍保留为历史记录；它们的 SHA 不代表本次修改后的工程。当前黑色睫毛／眼线仍隐藏，眉形开孔仍保留。

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
