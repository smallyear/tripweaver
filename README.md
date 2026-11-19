# 旅行规划师 (Travel Planner)

一个会和你逐条确认旅行细节、确认后一键生成**单文件方案书（HTML/PDF）**、**可缩放地图（HTML）**与**带文字行程的路线图（PNG）**的 WorkBuddy 专家。

两种用法并存：**当顾问**（门票多少钱、怎么坐车、明天天气——检索后直接答，标来源与月份，不出文件）；**当方案专家**（聊完给你一份能转发、能打印的完整方案 + 地图 + 海报）。

## 类型
Agent 型（单个 AI 专家）

## 功能
- **响应分级**：L1 顾问快答（单点事实，1–2 条检索，3 条以内，不出文件）/ L2 单日 / L3 多日全套 / L4 跨城自驾（加里程油费过路费）。
- **信息纪律**：价格、开放时间、预约政策必须实时检索，每条带来源与月份，冲突取官方并注区间；`trip.info_date` 会出现在所有交付物页脚。搜索问题库见 `references/research-method.md`。
- 分段访谈：目的地、天数、出行人、预算、兴趣、交通住宿、必去清单，每次只问 1–2 点。
- 动线预审：先核节点方位/进山门户/单日时长账，按同行人结构定节奏（带低龄儿童、带老人、纯成人各有参数），避免「一天塞六个点」和「首晚住到反向端点」。
- 确认闭环：草拟按天行程、每个主景点配雨天备选，循环修改直到你明确确认，才会出图。
- **方案书 plan.html**：七节（摘要 / 目的地调研 / 天气研判 / 逐日行程 / 路线图与动线 / 预算明细 / 出行清单），图片 base64 **内嵌成单文件**，手机可读、微信可转、浏览器可打印成 PDF（`--pdf` 自动导）。
- **预算明细**：六分项（大交通/住宿/门票/市内交通/餐饮/其他）+ 弹性预留 + 合计 + 人均，脚本校验合计；儿童/老人优惠票按假设计入并注明。
- 地图出图：底图按行程范围自动选择——中国大陆用高德（WGS-84 自动转 GCJ-02 贴合路网）、境外用 OSM；主底图加载失败自动回退备用底图。左侧文字行程 + 右侧可缩放路线图；另生成一张左文右图的 PNG 便于分享。地图标记旁常驻显示景点名，路线按序连成连续轨迹（首尾同名自动环线闭合）。
- **大交通不挤占地图**：首/末腿直线 > `trip.map_split_km`（默认 400km，即航班/长途高铁）会自动移出地图范围——不建标记、不参与缩放，改成一条灰虚线指向画布外 + 左下角提示条（`✈ 西安咸阳 → 丽江古城 · 直线约 1,173km · 08:25 → 15:30`），交互地图工具条可切「看全程」。`trip.map_scope="full"` 强制画全程，`stop.map_skip` 单点排除。分享图（海报/日卡）与 `plan.html` 内嵌海报同口径，不会再被拉到全国尺度。
- 自动地理编码：站点可不填经纬度，脚本按 **本地缓存 `references/poi-coords.json` → Photon（国内可达、支持中文）→ Nominatim(OSM)** 的顺序解析坐标（WGS-84）；多城行程建议填 `region`（如「陕西汉中」），**region 只用于归属校验**（Photon 对「前缀+地名」整串召回很差）。命中结果会做归属、名称重叠与 POI 类型三重校验，能挡住「跨省同名」「同名小地物（树/小径）」「县界标签点」这类静默错位；查不到的小地名明确提示手填坐标。来源坐标若是 GCJ-02（腾讯/高德/百度），标 `coord_source: "gcj02"` 或用 `bin/coord_convert.py` 先换算，避免标记偏 300~600m。
- 出图前自检：分 ❌ 阻断（结构性错误，退出码 1）与 ⚠️ 降级（无网络/缺 playwright/坐标缺失，仅告警不阻断）两级，详见下方「生成脚本」。
- 坐标核对表：打印每个站点的「来源 + 命中的行政层级 + osm 类型 + 距上一站直线距离」，便于一眼发现错位；`--geocode-only` 可只核对坐标、不出图（有缺失/低置信返回码 2），推荐**先核对再出图**。
- 出行前 Checklist：结合地理与日期给出提前预约时间线 + 天气/防虫/自然灾害/健康/证件/**避坑**等分类检查点，渲染成可勾选、可打印的 `checklist.html`。
- 实时气象：用 Open-Meteo（免密钥）按行程每天拉真实预报，渲染逐日天气卡 `weather.html`，并同步落 `weather.json` 供方案书内联；支持**临出发前再次调用**拉最新预报，把影响写回 `trip.day_impacts` 更新行程与清单。
- 手绘分享图：出图后另出一套**不带底图、手机尺寸**的分享图——每日海报（1080×1440）、封面（1600×1000）、景点速览（1200×1200）、金句卡（1080×1350），配手绘插画与手写体，可直接发朋友圈/群。插画按「每日头牌」生成，会消耗用户自己的积分（约 5–10 积分/张），**生成前先征求同意**。
- 四套视觉风格：地图 / 清单 / 气象 / 方案书四页共用一套主题，页面内可切**水彩手账（默认）/ 复古探险 / 简笔贴纸 / 原版导航风**，选择记在浏览器本地，四页联动（方案书页面另会同步纸张底色）。

## 使用示例
- 「故宫门票多少钱？需要提前预约吗」→ **L1 顾问快答**：检索后给价格/预约要求 + 来源月份，不出文件。
- 「我想规划一次旅行，请一步步帮我确认细节，最后生成方案书、可缩放地图和路线图。」
- 「帮我在成都规划 5 天，主打美食和慢生活的行程。」
- 确认后专家按序产出 `plan.html`（方案书）、`travel_map.html`、`route_map.png`；再按需出 `checklist.html`、`weather.html` 与 `share/` 分享图。
- 已给出「目的地 + 天数」时会走**快速通道**：直接给草稿 + 最多 3 个待定项，不必先答完问卷。

## 生成脚本
专家确认行程后会写出 `itinerary.json`（唯一数据源，字段见 `references/itinerary-schema.md`），再依次调用：

```bash
python3 bin/generate_travel.py   <itinerary.json> --out <输出目录>   # 地图 HTML + 路线 PNG
python3 bin/generate_weather.py  <itinerary.json> --out <输出目录>   # weather.html + weather.json
python3 bin/generate_checklist.py <checklist.json> --out <输出目录>  # checklist.html
python3 bin/generate_share.py    <itinerary.json> --out <输出目录>/share
python3 bin/generate_plan.py     <itinerary.json> --out <输出目录> [--pdf]  # 最后跑：汇总成方案书
```

### 方案书（plan.html）

```bash
python3 bin/generate_plan.py <itinerary.json> --out <输出目录> [--checklist <json>] [--weather <json>] [--no-embed] [--pdf]
```

- 纯静态渲染，**不联网、不需要 playwright**：读 `itinerary.json` + 同目录的 `weather.json` / `checklist.json` / `share/map_poster.png`。
- 七节：摘要（含信息基准日）/ 目的地调研 / 天气研判（逐日 + 对行程的影响）/ 逐日行程（含备选与站点事实）/ 路线图与每日动线 / 预算明细（六分项 + 弹性 + 人均）/ 出行清单。
- 图片默认 base64 内嵌 → **单文件**，微信发过去能直接看、离线可开。内嵌前会先用 macOS `sips` 把地图海报降到 1000px、转 JPEG(82)，单文件通常 **150–250KB**（原图直接内嵌会是 5MB）；`--no-embed` 改为相对路径引用，没有 `sips` 时自动退回原图内嵌。
- 内嵌的是 `share/map_poster.png`（纯地图海报），**不是** `route_map.png`（那是左文右图长图，与逐日行程重复且 2–3MB）。
- 内置自检：站点渲染数、预算合计、图片读取、占位符残留；缺 weather/checklist/research/budget 只告警不阻断。
- 打印机友好：`@media print` 隐藏按钮与风格切换、章节不跨页断裂；`--pdf` 用系统 Chrome 无头导出 `plan.pdf`（找不到 Chrome 仅告警）。

> 结构、降级规则、字段说明见 `references/plan-doc-guide.md`。

- 站点缺经纬度时，按 **缓存 → Photon → Nominatim** 顺序解析（WGS-84）；多城行程建议给每个 stop 填 `region`（如「陕西汉中」），它只用于归属校验。
- **先核对坐标再出图**：`--geocode-only` 只解析坐标并打印核对表后退出（有缺失/低置信返回码 2）；核完可加 `--dump-coords` 导出可直接粘贴进 `references/poi-coords.json` 的片段。
- **坐标系**：`itinerary.json` 一律存 WGS-84。腾讯/高德/政府公示是 GCJ-02（百度是 BD-09），标 `"coord_source": "gcj02"` 让脚本自动换算，或手动跑 `python3 bin/coord_convert.py gcj2wgs <lat> <lng>`。来源与坑位清单见 `references/coordinate-sources.md`。
- PNG 用浏览器截图：**优先复用系统已装的 Google Chrome**（无需下载 playwright 的 chromium），没有 Chrome 再退到系统 Edge、最后才用 playwright 自带 chromium。只需 `pip install playwright`，不必执行 `playwright install chromium`。
- 只想看可缩放地图时加 `--no-png` 可跳过 PNG。
- **出图前自检（默认开启）**：脚本运行后会自动打印一份自检报告，分两级：
  - **站点坐标核对表**：列出每个站点的解析坐标与来源（自动编码/手填），便于发现明显错位（如标到邻市）。
  - **❌ 阻断项**（退出码 1，须修复后重跑）：HTML 占位符残留 / 行程未渲染 / 站点数不符 / JS 错误 / PNG 左侧文字截断 / 行程超长。
  - **✅ 视觉核对项**：站点坐标与上一站距离、**景点常驻标签是否重叠**（脚本会自动微调标签位置避免压字，仍重叠时告警）。
  - **版面自适应**：行程文字远高于地图宽度时，PNG 自动改为「地图置顶 + 行程双栏」（否则地图会被拉成竖长条、底部大片空白）；短行程仍保持左右分栏。地图画幅高度按路线长宽比自适应（东西向路线用矮横幅、南北向用高画幅），缩放取 0.25 档，避免整数档导致路线只占画面一角。
  - **⚠️ 降级项**（仅告警，不阻断）：底图瓦片未加载（无网络时地图空白，文字行程仍可交付）/ 标记缺失（坐标缺失，手填后重跑）/ 未装 playwright（无 PNG）。
  - **底图自动回退**：主底图瓦片加载不足时自动切换备用底图（国内 高德→OSM，境外 OSM→CARTO）并打印 ℹ️ 提示。可用 `--skip-verify` 关闭自检（不推荐）。

### 手绘分享图（无地图）

```bash
python3 bin/generate_share.py <itinerary.json> --out <输出目录>/share [--types all|day,cover,grid,quote,map,mapday]
```

- 产出 `day_XX.png` 每日海报（1080×1440）、`cover_hero.png`（1600×1000）、`grid.png`（1200×1200 速览）、`quote_01..03.png`（1080×1350 金句卡），`device_scale_factor=2` 出高清图。
- **地图版**：`--types map` 出 `map_poster.png`（1080×1920+，方形地图 + 每日一行摘要，标签自动精简）；`--types mapday` 每天出一张 `map_day_XX.png`（1080×1350，当日路线 + 站点时间，只显示当天站点与路段，标签全量）。`all` 含 `map`、不含 `mapday`——每日地图卡更耗时，由用户决定是否要。地图版复用 `generate_travel` 的 Leaflet 页面截图，**不消耗 ImageGen 积分**，但需要网络拉瓦片。
- 不依赖地图底图，手写体走 macOS 系统字体栈（`HanziPen`/`Hannotate`/楷体），**不依赖外部 CDN**；渲染复用系统 Chrome。
- 插画放 `<行程目录>/illustrations/`，**磁盘文件名用中文真名**（`<站名>.png`，封面 `cover.png`）；HTML 里用 `encodeURIComponent` 引用。**不要把文件名写成 `%E9…` 百分号编码**——`file://` 会双重解码导致 404。
- 插画缺失不阻断：自动降级成「纸卡 + 站名」。插画由 ImageGen 生成、**消耗用户积分**，只画每日头牌（7 天封顶 7 张 + 封面），生成前先征得同意。
- 渲染后自带自检，逐张打印 ✅/⚠️/❌：**❌ = 文字溢出画布 / 页脚压住站点 / 图片加载失败**（退出码 1）；⚠️ = 插画缺失、九宫格可用插画不足 2 张（正常降级）。常驻景点名重叠时地图会自动上下/左右微调位置。
- 细节见 `references/share-guide.md`。

### 视觉风格

地图、清单、气象、方案书四页共用 localStorage 键 `tripweaver-theme`，页面右上角可切四套主题：**水彩手账（默认）/ 复古探险 / 简笔贴纸 / 原版**。手绘感不靠外部瓦片：路线抖动用 SVG `feTurbulence` 滤镜，手写体用系统字体栈，瓦片纸色化只用 CSS filter；复古主题可切到 Esri 无字地形底图。

### 出行前 Checklist

```bash
python3 bin/generate_checklist.py <checklist.json> --out <输出目录>
```

生成 `checklist.html`（可勾选、可打印，双击即开），无额外依赖。结构见 `references/checklist-guide.md`。

### 实时气象（可临出发再触发）

```bash
python3 bin/generate_weather.py <itinerary.json> --out <输出目录> [--today YYYY-MM-DD]
```

- 数据源 **Open-Meteo（免密钥）**，按站点坐标（或自动编码）拉每日预报：天气、温度区间、降水概率、风速。
- **每日取站规则**：天气/降水/风取「当天首个有坐标的站点」，**温度是当天各站点的区间**；卡片会标「数据取站：XX」，当天跨多地时另标「温度为各站区间」（如上午版纳 500m、晚上普洱 1300m，温差可达 10℃+），避免把单点温度误读成全行程温度。
- 预报窗口约 16 天：请求区间会**自动截断到窗口内**（避免末尾日期超窗导致整单 400），窗口外的日期显示「临近再查」并提示最晚何日再查；网络失败渲染「暂无实时数据」提示、**不阻断交付**。
- 规划时顺带出一版即可；**出发前 3–5 天带同一份 `itinerary.json` 再跑一次**，即得最新预报，并可并入 Checklist 的天气项。

## 底图与合规
底图按行程范围自动选择：**中国大陆用高德**（中文路网全，站点 WGS-84 坐标由脚本自动转 GCJ-02 贴合路网），**境外用 OSM**（WGS-84 直用）；主底图瓦片加载不足时自动回退备用底图，也可在 `itinerary.json` 的 `trip.basemap` 填 `amap`/`osm`/`carto` 强制指定。个人自用、不对外发布时无碍；若做中国内地地图产品并对外公开发布，需注意《地图审核管理规定》对底图数据源与坐标系（GCJ-02）的合规要求。

## 头像
头像已生成在 `avatars/expert.png`。如需替换，要求：PNG/JPG、512×512、≤500KB。

## 安装 / 注册
专家已注册到 marketplace，直接在专家中心选用即可。如需重新注册：

```bash
python3 scripts/register_expert.py <expert-dir>
```

## 打包分享

`dist/tripweaver.zip` 入库，是可直接上传的专家包。**源码改动后请在提交前重新打包**，否则包会落后于源码（曾发生过）：

```bash
bin/build_package.sh              # 输出 dist/tripweaver.zip，包内根目录为 tripweaver/
bin/build_package.sh /tmp/x.zip   # 也可指定输出路径
```

- 排除项：`.git`、`.gitignore`、`dist/`、`output/`、`.workbuddy/`、`__pycache__/`、`*.pyc`、`.DS_Store`、`*.log`。
- 打包前校验必需文件齐全（`plugin.json`、SOP、五个生成脚本、schema/share/调研/方案书指南、头像等），缺失即中止且**不覆盖已有包**；打包后做 `unzip -t` 完整性校验。
