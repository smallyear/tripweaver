# 旅行规划师 (Travel Planner)

一个会和你逐条确认旅行细节、确认后一键生成**可缩放地图（HTML）**与**带文字行程的路线图（PNG）**的 WorkBuddy 专家。

## 类型
Agent 型（单个 AI 专家）

## 功能
- 分段访谈：目的地、天数、出行人、预算、兴趣、交通住宿、必去清单，每次只问 1–2 点。
- 确认闭环：草拟按天行程，循环修改直到你明确确认，才会出图。
- 地图出图：基于 Leaflet + OpenStreetMap 底图，左侧文字行程 + 右侧可缩放路线图；另生成一张左文右图的 PNG 便于分享。地图标记旁常驻显示景点名，路线按序连成连续轨迹（首尾同名自动环线闭合）。
- 自动地理编码：站点可不填经纬度，脚本用 Nominatim 按「地名 + region（市县）」解析坐标；多城行程建议填 `region` 提升精度。
- 出图前自检：脚本运行后打印报告，含站点坐标核对表、HTML/图片完整性校验（瓦片加载≥80%、标记齐全、PNG 无截断），关键项失败则以退出码 1 阻断交付。
- 出行前 Checklist：结合地理与日期给出提前预约时间线 + 天气/防虫/自然灾害/健康/证件等分类检查点，渲染成可勾选、可打印的 `checklist.html`。
- 实时气象：用 Open-Meteo（免密钥）按行程每天拉真实预报，渲染逐日天气卡 `weather.html`；**支持临出发前再次调用**拉最新预报并更新 Checklist。

## 使用示例
- 「我想规划一次旅行，请一步步帮我确认细节，最后生成可缩放地图和带文字行程的路线图。」
- 「帮我在东京规划 5 天，主打美食和购物的行程。」
- 确认后专家自动产出 `travel_map.html` 与 `route_map.png`。

## 生成脚本
专家确认行程后会写出 `itinerary.json`，并调用：

```bash
python3 bin/generate_travel.py <itinerary.json> --out <输出目录>
```

- 站点缺经纬度时，自动用 Nominatim(OSM) 按地名 + `region` 地理编码（WGS-84）；多城行程建议给每个 stop 填 `region`（如「陕西汉中」）。
- PNG 需要 Playwright：`pip install playwright && playwright install chromium`。
- 只想看可缩放地图时加 `--no-png` 可跳过 PNG。
- **出图前自检（默认开启）**：脚本运行后会自动打印一份自检报告，覆盖：
  - **站点坐标核对表**：列出每个站点的解析坐标与来源（自动编码/手填），便于发现明显错位（如标到邻市）。
  - **HTML 正确性**：无占位符残留 / 无 JS 错误 / 行程与站点数渲染正常。
  - **图片完整性**：地图瓦片已加载（**已加载比例 ≥ 80% 否则判失败**）、标记齐全、PNG 左侧文字行程无截断、尺寸正常。
  - 任何关键项报 ❌ 时脚本以退出码 1 中止，提醒先排查再交付。可加 `--skip-verify` 关闭（不推荐）。

### 出行前 Checklist

```bash
python3 bin/generate_checklist.py <checklist.json> --out <输出目录>
```

生成 `checklist.html`（可勾选、可打印，双击即开），无额外依赖。结构见 `references/checklist-guide.md`。

### 实时气象（可临出发再触发）

```bash
python3 bin/generate_weather.py <itinerary.json> --out <输出目录> [--today YYYY-MM-DD]
```

- 数据源 **Open-Meteo（免密钥）**，按站点坐标（或 Nominatim 自动编码）拉每日预报：天气、温度区间、降水概率、风速。
- 预报窗口约 16 天：超出窗口的日期显示「临近再查」并提示最晚何日再查；网络失败渲染「暂无实时数据」提示、**不阻断交付**。
- 规划时顺带出一版即可；**出发前 3–5 天带同一份 `itinerary.json` 再跑一次**，即得最新预报，并可并入 Checklist 的天气项。

## 底图与合规
默认采用 Leaflet + OpenStreetMap（WGS-84）作为底图。OSM 为境外通用底图，适合个人查看与境外行程。若要做**中国内地**并对外公开发布，需注意《地图审核管理规定》对底图数据源与坐标系（GCJ-02）的合规要求；个人自用、不对外发布时通常无碍。

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
