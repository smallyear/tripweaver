# itinerary.json 结构规范

专家在用户确认行程后，输出如下结构的 JSON，传入 `bin/generate_travel.py` 生成地图。

```json
{
  "trip": {
    "title": "行程标题",
    "destination": "目的地（地理编码上下文）",
    "start_date": "2026-10-01",
    "days": 5,
    "travelers": "2人（情侣）",
    "budget": "¥15000",
    "theme": "文化/美食",
    "pace": "松弛"
  },
  "stops": [
    {
      "day": 1,
      "time": "09:00",
      "name": "伏见稻荷大社",
      "lat": 34.967,
      "lng": 135.772,
      "note": "千本鸟居，建议早到"
    }
  ]
}
```

## 字段说明

- `trip`：行程概览，尽量填全，用于左侧文字面板与图片标题。
- `stops[]`：按时间排序的站点数组。
  - `day`（必填）：第几天，整数。
  - `name`（必填）：地点名，用于地图标注与地理编码。
  - `time`（可选）：时间，如 "09:00"。
  - `note`（可选）：备注/理由。
  - `lat` / `lng`（可选）：经纬度（WGS-84，与 OSM 一致）。**留空时脚本用 Nominatim 按 `name`+`region`/`destination` 自动解析**；给出则覆盖自动解析。
  - `region`（可选）：地理编码上下文（市/县，如「陕西汉中」「四川广元」）。多城环线下**强烈建议填写**，比用整条 `destination` 作上下文更准，能避免把地点解析到错误城市。

## 生成命令

```bash
python3 bin/generate_travel.py itinerary.json --out ./output
```

生成 `travel_map.html`（可缩放地图）与 `route_map.png`（左文右图整图）。
PNG 需要 playwright：`pip install playwright && playwright install chromium`。
