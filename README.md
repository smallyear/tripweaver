# 旅行规划师 (Travel Planner)

一个会和你逐条确认旅行细节、确认后一键生成**可缩放地图（HTML）**与**带文字行程的路线图（PNG）**的 WorkBuddy 专家。

## 类型
Agent 型（单个 AI 专家）

## 功能
- 分段访谈：目的地、天数、出行人、预算、兴趣、交通住宿、必去清单，每次只问 1–2 点。
- 确认闭环：草拟按天行程，循环修改直到你明确确认，才会出图。
- 地图出图：底图按行程范围自动选择——中国大陆用高德（WGS-84 自动转 GCJ-02 贴合路网）、境外用 OSM；主底图加载失败自动回退备用底图。左侧文字行程 + 右侧可缩放路线图；另生成一张左文右图的 PNG 便于分享。地图标记旁常驻显示景点名，路线按序连成连续轨迹（首尾同名自动环线闭合）。
- 自动地理编码：站点可不填经纬度，脚本按 **本地缓存 `references/poi-coords.json` → Photon（国内可达、支持中文）→ Nominatim(OSM)** 的顺序解析坐标（WGS-84）；多城行程建议填 `region`（如「陕西汉中」），**region 只用于归属校验**（Photon 对「前缀+地名」整串召回很差）。命中结果会做归属、名称重叠与 POI 类型三重校验，能挡住「跨省同名」「同名小地物（树/小径）」「县界标签点」这类静默错位；查不到的小地名明确提示手填坐标。来源坐标若是 GCJ-02（腾讯/高德/百度），标 `coord_source: "gcj02"` 或用 `bin/coord_convert.py` 先换算，避免标记偏 300~600m。
- 出图前自检：分 ❌ 阻断（结构性错误，退出码 1）与 ⚠️ 降级（无网络/缺 playwright/坐标缺失，仅告警不阻断）两级，详见下方「生成脚本」。
- 坐标核对表：打印每个站点的「来源 + 命中的行政层级 + osm 类型 + 距上一站直线距离」，便于一眼发现错位；`--geocode-only` 可只核对坐标、不出图（有缺失/低置信返回码 2），推荐**先核对再出图**。
- 出行前 Checklist：结合地理与日期给出提前预约时间线 + 天气/防虫/自然灾害/健康/证件等分类检查点，渲染成可勾选、可打印的 `checklist.html`。
- 实时气象：用 Open-Meteo（免密钥）按行程每天拉真实预报，渲染逐日天气卡 `weather.html`；**支持临出发前再次调用**拉最新预报并更新 Checklist。

## 使用示例
- 「我想规划一次旅行，请一步步帮我确认细节，最后生成可缩放地图和带文字行程的路线图。」
- 「帮我在成都规划 5 天，主打美食和慢生活的行程。」
- 确认后专家自动产出 `travel_map.html` 与 `route_map.png`。

## 生成脚本
专家确认行程后会写出 `itinerary.json`，并调用：

```bash
python3 bin/generate_travel.py <itinerary.json> --out <输出目录>
```

- 站点缺经纬度时，按 **缓存 → Photon → Nominatim** 顺序解析（WGS-84）；多城行程建议给每个 stop 填 `region`（如「陕西汉中」），它只用于归属校验。
- **先核对坐标再出图**：`--geocode-only` 只解析坐标并打印核对表后退出（有缺失/低置信返回码 2）；核完可加 `--dump-coords` 导出可直接粘贴进 `references/poi-coords.json` 的片段。
- **坐标系**：`itinerary.json` 一律存 WGS-84。腾讯/高德/政府公示是 GCJ-02（百度是 BD-09），标 `"coord_source": "gcj02"` 让脚本自动换算，或手动跑 `python3 bin/coord_convert.py gcj2wgs <lat> <lng>`。来源与坑位清单见 `references/coordinate-sources.md`。
- PNG 用浏览器截图：**优先复用系统已装的 Google Chrome**（无需下载 playwright 的 chromium），没有 Chrome 再退到系统 Edge、最后才用 playwright 自带 chromium。只需 `pip install playwright`，不必执行 `playwright install chromium`。
- 只想看可缩放地图时加 `--no-png` 可跳过 PNG。
- **出图前自检（默认开启）**：脚本运行后会自动打印一份自检报告，分两级：
  - **站点坐标核对表**：列出每个站点的解析坐标与来源（自动编码/手填），便于发现明显错位（如标到邻市）。
  - **❌ 阻断项**（退出码 1，须修复后重跑）：HTML 占位符残留 / 行程未渲染 / 站点数不符 / JS 错误 / PNG 左侧文字截断 / 行程超长。
  - **⚠️ 降级项**（仅告警，不阻断）：底图瓦片未加载（无网络时地图空白，文字行程仍可交付）/ 标记缺失（坐标缺失，手填后重跑）/ 未装 playwright（无 PNG）。
  - **底图自动回退**：主底图瓦片加载不足时自动切换备用底图（国内 高德→OSM，境外 OSM→CARTO）并打印 ℹ️ 提示。可用 `--skip-verify` 关闭自检（不推荐）。

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
```bash
zip -r travel-planner.zip travel-planner/
```
