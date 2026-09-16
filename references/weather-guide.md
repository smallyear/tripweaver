# 实时气象规范

本文件说明旅行规划师的「实时气象」能力（Phase 6）的数据来源、字段含义与**重调用法**。

## 数据源

- **Open-Meteo**（https://open-meteo.com）：免费、**无需 API Key**，按经纬度返回每日天气预报。
- 脚本：`bin/generate_weather.py`，输入 `itinerary.json`，输出 `weather.html`。
- 站点坐标：优先用 `stops[].lat/lng`；缺失则按 `name` + `region`（或 `destination`）用 Nominatim 自动地理编码。

## 取哪些字段

| 字段 | 含义 | 用途 |
|---|---|---|
| `weathercode` | WMO 天气代码 | 映射成 emoji + 中文描述（见下表） |
| `temperature_2m_max/min` | 当日最高/最低温 | 穿衣与保暖提示 |
| `precipitation_probability_max` | 当日最大降水概率(%) | 带伞/雨衣决策 |
| `windspeed_10m_max` | 最大风速(km/h) | 海边/山区/防风提示 |

### WMO weathercode 映射（节选）

- 0 晴 ☀️ ｜ 1 大致晴朗 🌤️ ｜ 2 局部多云 ⛅ ｜ 3 阴 ☁️
- 45/48 雾 🌫️ ｜ 51–57 毛毛雨/冻毛毛雨 🌦️🌧️
- 61/63/65 雨 🌧️ ｜ 66/67 冻雨 🌧️ ｜ 71/73/75 雪 🌨️ ｜ 77 雪粒 🌨️
- 80–82 阵雨 🌦️ ｜ 85/86 阵雪 🌨️ ｜ 95/96/99 雷阵雨(伴冰雹) ⛈️

## 预报窗口与重调用法（关键）

Open-Meteo 预报窗口约 **16 天**。因此气象分两次使用：

1. **规划时（Phase 5 之后，可选）**：若出发日在 16 天内，可一并出 `weather.html` 并并入 Checklist；若 >16 天，脚本对超窗日期显示「临近再查」，并提示最晚何日再查——此时**不**把无数据项塞进清单。
2. **临出发再调用（重点）**：用户带着当初的 `itinerary.json` 再次打开本专家，说「查一下天气 / 更新气象」，专家重跑脚本拉**最新**预报，展示 `weather.html`，并（用户同意时）把天气要点并入 `checklist.json` 的 `weather` 分类与 `notes`，重出 `checklist.html`。

无论哪次，都提醒用户：**出发前 1–2 天再看最后一次更新**——气象会随时间变化。

## 健壮性

- 网络不可用：脚本渲染「暂无实时数据」提示，**不阻断交付**，终端打印告警。
- 坐标缺失且地理编码失败：该日天气留空，其余正常。

## 生成命令

```bash
python3 bin/generate_weather.py <itinerary.json> --out <输出目录> [--today YYYY-MM-DD]
```

`--today` 用于测试（覆盖系统日期）。生成 `weather.html`（可打印）。
