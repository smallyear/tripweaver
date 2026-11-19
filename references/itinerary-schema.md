# itinerary.json 结构规范

专家在用户确认行程后输出本文件，它是后续所有产物的**唯一数据源**：

```bash
python3 bin/generate_travel.py  itinerary.json --out <目录>   # 交互地图 + 路线 PNG
python3 bin/generate_weather.py itinerary.json --out <目录>   # 逐日气象（+ weather.json）
python3 bin/generate_plan.py    itinerary.json --out <目录>   # 单文件方案书 plan.html（+ PDF）
```

## 完整示例

```json
{
  "trip": {
    "title": "西双版纳 7 日雨林慢游",
    "destination": "云南西双版纳",
    "start_date": "2026-11-28",
    "days": 7,
    "travelers": "3人（2大人+1儿童6岁）",
    "theme": "雨林/亲子",
    "pace": "松弛",
    "basemap": "amap",
    "info_date": "2026-11-18",
    "map_scope": "local",
    "map_split_km": 400,
    "day_themes": { "1": "抵达·告庄夜游", "2": "雨林徒步" },
    "climate_note": "11 月下旬进入旱季初期，白天 25–28℃、早晚 12–15℃，午后偶有阵雨",
    "day_impacts": { "2": "有雨 → 上午改室内备选（民族博物馆）" },
    "research": [
      {
        "title": "必去清单",
        "items": ["中科院植物园 — 雨林科普，孩子能摸到含羞草", "野象谷 — 亚洲象近距离观察"],
        "table": {
          "head": ["景点", "门票", "儿童/老人", "预约", "来源"],
          "rows": [["野象谷", "¥65", "1.2m 以下免票", "旺季需提前 1 天", "官网 2026-11"]]
        },
        "source": "西双版纳文旅 / 各景区官网",
        "date": "2026-11"
      }
    ],
    "budget": {
      "basis": "3 人总计",
      "pax": 3,
      "currency": "CNY",
      "contingency_pct": 10,
      "items": [
        { "cat": "大交通", "detail": "运城 ↔ 昆明/版纳 往返 ×3", "amount": 6000, "note": "含中转" },
        { "cat": "住宿", "detail": "6 晚 × 1 间三人房", "amount": 3000, "note": "告庄 + 植物园" },
        { "cat": "门票", "detail": "植物园/野象谷/望天树", "amount": 1500, "note": "儿童按免票计" }
      ]
    }
  },
  "stops": [
    {
      "day": 1,
      "time": "09:00",
      "name": "宽窄巷子",
      "lat": 30.669,
      "lng": 104.057,
      "note": "建议早到避开人潮",
      "alt": "人民公园鹤鸣茶社（雨天备选）",
      "facts": [{ "k": "门票", "v": "免费", "src": "官网", "date": "2026-11" }]
    }
  ]
}
```

## 字段说明

### `trip`

| 字段 | 必填 | 说明 |
|---|---|---|
| `title` / `destination` | ✅ | 标题用于页面与分享图；`destination` 同时是地理编码上下文，**写短名**（「云南西双版纳」，不要把出发地塞进来） |
| `start_date` / `days` | ✅ | `YYYY-MM-DD` / 整数 |
| `travelers` | ✅ | 结构描述（几人、什么关系、孩子年龄），分享图与预算人均会用 |
| `theme` / `pace` | ✅ | 主题标签 / 松弛·紧凑 |
| `info_date` | ✅ | **信息基准日**，所有交付物页脚都会显示「基于该日检索，出发前请复核」 |
| `budget` | ✅ | 对象（见下）或旧版字符串（`"¥15000"`，兼容保留，只显示不拆表） |
| `research` | 建议 | 目的地调研块数组：`title` + `items[]`（要点）/ `table`（结构化表）+ `source` + `date` |
| `day_themes` | 可选 | `{"1": "抵达·夜市"}`，逐日主题小标题 |
| `climate_note` | 可选 | 规划期气候研判（一句话），渲染在「天气研判」表上方 |
| `day_impacts` | 可选 | `{"2": "有雨 → 上午改室内"}`，天气对当日行程的影响，由专家据预报填写 |
| `basemap` | 可选 | `amap` / `osm` / `carto` / `esri_physical`；不填按站点范围自动选 |
| `map_scope` | 可选 | `local`（默认）把大交通移出地图范围；`full` 强制画全程（跨省大环线会变全国尺度） |
| `map_split_km` | 可选 | 判定“大交通”的直线距离阈值，默认 400km；只切首/末腿 |
| `click_zoom` / `collapsed_days` | 可选 | 地图点击缩放级别 / 默认折叠的天 |

### `trip.budget`

| 字段 | 说明 |
|---|---|
| `basis` | 口径说明：「3 人总计」或「人均」 |
| `pax` | 人数，用于算人均；缺省从 `travelers` 里取第一个数字 |
| `contingency_pct` | 弹性预留百分比，默认 10 |
| `items[]` | `cat`（大交通/住宿/门票/市内交通/餐饮/其他）、`detail`、`amount`、`note` |

预算由 `generate_plan.py` 渲染成表格并**校验合计**：`合计 = 明细之和`，`弹性 = 合计 × pct`，`含弹性合计`、`人均` 自动算。
价格有多来源冲突时按官方价计入 `amount`，区间写在 `note`。

### `stops[]`

| 字段 | 必填 | 说明 |
|---|---|---|
| `day` | ✅ | 第几天（整数） |
| `name` | ✅ | 地点名（地图标注 + 地理编码） |
| `time` | 可选 | `"09:00"` 或 `"上午"` |
| `note` | 可选 | 一句话理由/提醒 |
| `alt` | 可选 | **备选方案**（雨天/预约失败），进 `plan.html` 与地图侧栏，不上地图标记 |
| `map_skip` | 可选 | `true` = 强制移出地图范围（不进包围盒、不建标记，但仍画虚线+提示条） |
| `facts` | 可选 | 该站点的关键事实：`{k 名称, v 值, src 来源, date 月份}`，plan.html 渲染成小表 |
| `lat` / `lng` | 可选 | WGS-84。留空时按「缓存 → Photon → Nominatim」解析 |
| `region` | 可选 | 地理编码归属校验（「陕西汉中」），多城行程**强烈建议填** |
| `coord_source` | 可选 | 来源是 GCJ-02 时填 `"gcj02"`，脚本自动换算 |

## 地图范围纪律（大交通与区内动线分开）

出发地/返程地如果是航班或长途高铁（如「西安 ✈ 丽江」1191km），它会把地图包围盒撑到 1500km 级，
而区内动线只有 110km —— 比例尺差十几倍，地图上 90% 是空白、景点挤成一坨。

`generate_travel.py` 的 `compute_map_scope()` 会自动处理，**不需要在 JSON 里手工标注**：

1. 只切**首腿/末腿**，且直线 > `map_split_km`（默认 400）才切；
2. 被切的站点标 `offmap`：不建标记、不参与 `fitBounds`，但仍画一条**灰虚线指向画布外**；
3. 地图左下角出现提示条：`✈ 西安咸阳国际机场 → 丽江古城 · 直线约 1,173 km · 08:25 → 15:30 · 大交通未按比例绘制`；
4. 交互地图工具条多一个「看全程」，一键切回全国尺度（PNG 与分享图默认只出区内）；
5. 中间的长腿（如 D3 昆明→版纳）暂不切——切了会变成多块图，见 `docs/TODO.md`。

## 坐标纪律

1. 一律存 **WGS-84**。腾讯/高德/政府公示是 GCJ-02，百度是 BD-09（见 `references/coordinate-sources.md`）。
2. 出图前先 `generate_travel.py <itin> --geocode-only` 核对坐标表，无缺失/低置信再出图。
3. 核实过的冷门 POI 用 `--dump-coords` 回写 `references/poi-coords.json`。
