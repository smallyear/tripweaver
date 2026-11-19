# 方案书 plan.html 规范

`plan.html` 是**一份能读、能转发、能打印**的完整旅行方案书，与交互地图（自己看路线）、分享图（发朋友圈）分工不同：

| 产物 | 谁看 | 场景 |
|---|---|---|
| `plan.html` | 同行人、家人、同事 | 微信发过去就能读；打印成 PDF 带着走 |
| `travel_map.html` | 你自己 | 放大地图看每个站点、点站点联动 |
| `route_map.png` | 需要一张图的人 | 单张左文右图长图 |
| `share/*.png` | 朋友圈、群 | 手机原生比例、缩略可读 |

## 命令

```bash
python3 bin/generate_plan.py <itinerary.json> --out <目录> [--checklist checklist.json] [--pdf] [--no-embed]
```

- `--out` 省略时写到 itinerary 同目录；产物 `plan.html`。
- 数据来源全部读取，不联网、不调模型：`itinerary.json`（必需）+ `checklist.json`（可选）+ `weather.json`（可选）+ `share/map_poster.png`（可选）。
- `--embed`（默认开启）把图片 base64 内嵌，得到一个**单文件**：微信发过去能直接看、离线也能开。
  内嵌前会用 macOS `sips` 把地图海报降到 1000px、转 JPEG(82)——原图可达 4MB，降完单文件通常 150–250KB。没有 `sips`（非 macOS）时退回原图内嵌，文件会到 MB 级。
  加 `--no-embed` 改为相对路径引用（体积最小，但必须整个文件夹一起发）。
- `--pdf` 用系统 Chrome 无头打印出 `plan.pdf`（A4、保留分页样式）；找不到 Chrome 只告警，不影响 HTML。

## 七节结构（顺序固定，章节名可微调）

| 节 | 内容来源 | 说明 |
|---|---|---|
| 0 封面/摘要 | `trip.*` | 标题、日期区间、天数、同行人、总预算、节奏 + **信息基准日徽标** |
| 1 目的地调研 | `trip.research[]` | 每块：标题 + 要点列表 / 结构化表 + 来源小注 |
| 2 天气研判 | `weather.json` + `trip.climate_note` + `trip.day_impacts` | 逐日表：日期 / 天气 / 温度 / 降水 / **对当日行程的影响**；无数据时降级提示 |
| 3 逐日行程 | `stops[]` + `day_themes` | 每天：主题 + 时间轴站点（时间/名称/理由）+ 备选徽标 + `facts` 小表 |
| 4 路线图与动线 | `share/map_poster.png` + `stops[]` | 内嵌**全程地图海报**；每日动线文字由脚本自动从站点顺序生成（不手工写）。**不内嵌 `route_map.png`**——那是「地图置顶+行程双栏」整图，与逐日行程重复且 2–3MB |
| 5 预算明细 | `trip.budget` | 六分项表 + 合计 + 弹性 + 含弹性合计 + 人均；脚本校验合计 |
| 6 出行清单 | `checklist.json` | 时间线 + 分类检查项（页面内可勾选）+ 特别提醒 |

页脚固定显示：信息基准日 / 生成时间 / 边界声明（不代订、不办签证、不买保险）。

## 数据缺失时的降级（不阻断交付）

| 缺什么 | 表现 |
|---|---|
| `weather.json` | 天气节显示「尚未取到实时预报」，并提示先跑 `generate_weather.py` |
| `checklist.json` | 清单节显示提示 + 一句「可单独生成 checklist.html」 |
| `share/map_poster.png` | 路线图节降级为提示（先跑 `generate_share.py --types map`），动线文字照常输出 |
| `trip.budget.items` | 预算节只显示 `trip.budget` 原文（兼容旧字符串） |
| `trip.research` | 调研节整节省略（不产出空标题） |

## 自检（脚本内置，退出码 1 = 不要交付）

- ❌ 占位符残留 / 站点渲染数与 JSON 不一致 / 预算明细之和与手写合计不符 / 内嵌图片读取失败
- ⚠️ 缺 weather / checklist / research / budget 明细（降级项，如实告知用户即可）

## 打印与 PDF

页面自带 `@media print`：隐藏风格切换与按钮、卡片去掉阴影、避免章节跨页断裂。
浏览器里「打印 → 存储为 PDF」即可；`--pdf` 只是把这一步自动化（需要系统 Chrome）。

## 与其他产物的一致性

- 站点顺序、名称、时间与 `travel_map.html` / 分享图**同源**，改行程只改 `itinerary.json` 一处，再重跑三个脚本。
- 信息基准日 `trip.info_date` 会同时出现在 `plan.html`、`travel_map.html`、`checklist.html`、`weather.html` 的页脚。
- 交付时别把 `plan.html` 与 `checklist.html`、`weather.html` 重复发一遍：**plan.html 已内联清单与气象**，另两个是给「想单独勾选/单独看天气」的人。
