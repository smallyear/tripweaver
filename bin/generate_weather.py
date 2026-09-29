#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_weather.py - 行程天气预报生成器

读取 itinerary.json（含每天站点的 lat/lng，或 name+region 自动地理编码），
用 Open-Meteo（免 API Key）按行程每天拉取真实天气预报，渲染成 weather.html。

产物：
  - weather.html ：逐日天气卡（天气 / 温度区间 / 降水概率 / 风速）+ 出行提示，可打印。
  - 终端会同时打印一段精简文字简报，供专家回填进 Checklist 的天气项。

用法：
  python3 generate_weather.py <itinerary.json> --out <输出目录> [--today YYYY-MM-DD]

说明：
  - Open-Meteo 免费、无需密钥，预报窗口约 16 天。若行程开始日超出该窗口，
    脚本会逐日判断：有数据则出真实预报，无数据则标「临近再查」，并提示最晚何日再跑。
  - 网络不可用时渲染「暂无实时数据」提示，不阻断交付。
"""

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_travel import geocode as _geocode  # noqa: E402  复用出图脚本已加固的地理编码

MAX_LEAD_DAYS = 16  # Open-Meteo 预报窗口（天，含今天共 16 天）

# WMO weathercode -> (emoji, 中文描述)
WMO = {
    0: ("☀️", "晴"),
    1: ("🌤️", "大致晴朗"),
    2: ("⛅", "局部多云"),
    3: ("☁️", "阴"),
    45: ("🌫️", "雾"),
    48: ("🌫️", "雾凇"),
    51: ("🌦️", "小毛毛雨"),
    53: ("🌦️", "毛毛雨"),
    55: ("🌦️", "大毛毛雨"),
    56: ("🌧️", "冻毛毛雨"),
    57: ("🌧️", "强冻毛毛雨"),
    61: ("🌧️", "小雨"),
    63: ("🌧️", "中雨"),
    65: ("🌧️", "大雨"),
    66: ("🌧️", "冻雨"),
    67: ("🌧️", "强冻雨"),
    71: ("🌨️", "小雪"),
    73: ("🌨️", "中雪"),
    75: ("🌨️", "大雪"),
    77: ("🌨️", "雪粒"),
    80: ("🌦️", "小阵雨"),
    81: ("🌦️", "阵雨"),
    82: ("🌦️", "强阵雨"),
    85: ("🌨️", "阵雪"),
    86: ("🌨️", "强阵雪"),
    95: ("⛈️", "雷阵雨"),
    96: ("⛈️", "雷阵雨伴小冰雹"),
    99: ("⛈️", "雷阵雨伴大冰雹"),
}

UA = "travel-planner/1.0 (workbuddy; +https://www.workbuddy.cn)"


class OutOfWindow(Exception):
    """请求的日期超出 Open-Meteo 预报窗口（约 16 天），并非网络错误。"""

    pass


def wmo_info(code):
    return WMO.get(int(code), ("❓", "未知天气"))


def geocode(name, region, destination):
    """把地名解析成 (lat, lng)；失败返回 None。

    直接复用 generate_travel.py 的 geocode（Photon 优先 + 本地坐标缓存 + Nominatim 兜底），
    避免两个脚本各维护一份解析逻辑而行为不一致。其返回 (lat, lng, meta)，此处只取坐标。
    """
    lat, lng, _meta = _geocode(name, region or destination or "")
    return (lat, lng) if lat is not None else None


def forecast_for(lat, lng, start, end):
    """Open-Meteo 一次调用取 [start,end] 区间每日预报，返回 {date: {...}}。

    注意：end 超出预报窗口时接口直接返回 400（整单失败），调用方须先把 end 截断到
    窗口内再调用；此处仍保留 OutOfWindow 兜底，供调用方逐日收窄重试。
    """
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(
        {
            "latitude": f"{lat:.4f}",
            "longitude": f"{lng:.4f}",
            "daily": "weathercode,temperature_2m_max,temperature_2m_min,"
            "precipitation_probability_max,windspeed_10m_max",
            "timezone": "auto",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        }
    )
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            d = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 400:
            # 日期超出预报窗口，而非网络故障
            raise OutOfWindow()
        raise
    out = {}
    daily = d.get("daily", {})
    times = daily.get("time", [])
    for i, t in enumerate(times):
        out[t] = {
            "code": daily.get("weathercode", [None] * len(times))[i],
            "tmax": daily.get("temperature_2m_max", [None] * len(times))[i],
            "tmin": daily.get("temperature_2m_min", [None] * len(times))[i],
            "rain": daily.get("precipitation_probability_max", [None] * len(times))[i],
            "wind": daily.get("windspeed_10m_max", [None] * len(times))[i],
        }
    return out


def esc(s):
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("json_path")
    ap.add_argument("--out", default=".")
    ap.add_argument("--today", default=None, help="覆盖今天的日期 YYYY-MM-DD")
    args = ap.parse_args()

    today = (
        datetime.strptime(args.today, "%Y-%m-%d").date()
        if args.today
        else date.today()
    )

    with open(args.json_path, encoding="utf-8") as f:
        data = json.load(f)

    trip = data.get("trip", {})
    title = trip.get("title", "行程天气预报")
    destination = trip.get("destination", "")
    start_date = datetime.strptime(trip["start_date"], "%Y-%m-%d").date()
    days = int(trip.get("days", 1))
    end_date = start_date + timedelta(days=days - 1)

    stops = data.get("stops", [])
    # 按天分组
    by_day = {}
    for s in stops:
        by_day.setdefault(int(s.get("day", 1)), []).append(s)

    # 解析每天坐标：收集当天「所有站点」的坐标（不止第一个），
    # 既能标注数据取站，也能在当天跨多地时给出温度区间（如野象谷→普洱当天温差很大）。
    cache = {}
    day_coords = {}
    day_rep = {}
    geo_fail = False  # 站点未填坐标且解析失败，多为网络/服务不可达
    for d in range(1, days + 1):
        coords, rep = [], ""
        for s in by_day.get(d, []):
            if s.get("lat") is None or s.get("lng") is None:
                continue
            c = (float(s["lat"]), float(s["lng"]))
            if (round(c[0], 4), round(c[1], 4)) not in [(round(x[0], 4), round(x[1], 4)) for x in coords]:
                coords.append(c)
                if not rep:
                    rep = s.get("name", "")
        if not coords and by_day.get(d):
            s0 = by_day[d][0]
            key = (s0.get("name"), s0.get("region"), destination)
            if key not in cache:
                cache[key] = geocode(s0.get("name"), s0.get("region"), destination)
            if cache[key]:
                coords = [cache[key]]
                rep = s0.get("name", "")
            else:
                geo_fail = True
        day_coords[d] = coords
        day_rep[d] = rep

    # 唯一坐标集合，每坐标一次调用
    unique = {}
    for d in range(1, days + 1):
        for c in day_coords.get(d, []):
            unique.setdefault((round(c[0], 4), round(c[1], 4)), c)
    # 预报窗口：只覆盖今天起约 16 天。把请求区间截断到窗口内——否则末尾日期超窗会让
    # 接口对整单返回 400，连窗口内那几天也一起丢掉（窗口外的日子照常显示「临近再查」）。
    window_end = today + timedelta(days=MAX_LEAD_DAYS - 1)
    req_start = max(start_date, today)
    req_end = min(end_date, window_end)

    forecasts = {}
    net_ok = True
    if req_start <= req_end:
        for key, (lat, lng) in unique.items():
            end_try = req_end
            while True:
                try:
                    forecasts[key] = forecast_for(lat, lng, req_start, end_try)
                    break
                except OutOfWindow:
                    # 兜底：仍被判超窗就逐日收窄重试，保证窗口内的日子照常出预报
                    if end_try <= req_start:
                        break
                    end_try -= timedelta(days=1)
                except Exception as e:  # noqa: BLE001
                    print(f"  ⚠️ 获取预报失败 ({lat},{lng}): {e}", file=sys.stderr)
                    net_ok = False
                    break

    def day_weather(d):
        """当日预报汇总：天气/降水/风取代表站（当天首个有坐标的站点），温度取当天各站区间。"""
        coords = day_coords.get(d) or []
        if not coords:
            return None
        dt = (start_date + timedelta(days=d - 1)).isoformat()
        recs = []
        for c in coords:
            f = forecasts.get((round(c[0], 4), round(c[1], 4)))
            if f and f.get(dt):
                recs.append(f[dt])
        if not recs:
            return None
        tmins = [r["tmin"] for r in recs if r.get("tmin") is not None]
        tmaxs = [r["tmax"] for r in recs if r.get("tmax") is not None]
        return {
            "code": recs[0].get("code"),
            "rain": max((r["rain"] for r in recs if r.get("rain") is not None), default=None),
            "wind": recs[0].get("wind"),
            "tmin": min(tmins) if tmins else None,
            "tmax": max(tmaxs) if tmaxs else None,
            "multi": len(recs) > 1,
        }

    # 构建逐日卡片数据
    cards = []
    any_data = False
    for d in range(1, days + 1):
        dt = start_date + timedelta(days=d - 1)
        w = day_weather(d)
        names = [s.get("name", "") for s in by_day.get(d, [])]
        if w and w.get("code") is not None:
            any_data = True
            emoji, desc = wmo_info(w["code"])
            cards.append(
                {
                    "day": d,
                    "date": dt.isoformat(),
                    "weekday": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][
                        dt.weekday()
                    ],
                    "places": names,
                    "station": day_rep.get(d, ""),
                    "multi": bool(w.get("multi")),
                    "emoji": emoji,
                    "desc": desc,
                    "tmax": w["tmax"],
                    "tmin": w["tmin"],
                    "rain": w["rain"],
                    "wind": w["wind"],
                    "available": True,
                }
            )
        else:
            cards.append(
                {
                    "day": d,
                    "date": dt.isoformat(),
                    "weekday": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][
                        dt.weekday()
                    ],
                    "places": names,
                    "available": False,
                }
            )

    # 出行提示（基于有数据的日子）
    tips = []
    if any_data:
        max_rain = max(
            (c["rain"] for c in cards if c["available"] and c["rain"] is not None),
            default=0,
        )
        min_t = min(
            (c["tmin"] for c in cards if c["available"] and c["tmin"] is not None),
            default=99,
        )
        max_t = max(
            (c["tmax"] for c in cards if c["available"] and c["tmax"] is not None),
            default=-99,
        )
        if max_rain and max_rain >= 60:
            tips.append("多日降水概率偏高，务必带伞/雨衣，户外行程预留室内备选。")
        if min_t <= 5:
            tips.append(f"夜间/清晨最低约 {min_t}°C，注意保暖与分层穿搭。")
        if max_t >= 33:
            tips.append(f"日间最高约 {max_t}°C，注意防晒、补水，避免长时间暴晒。")
        if not tips:
            tips.append("近期天气平稳，按常规出行准备即可；出发前 1–2 天再看一次更新。")
    else:
        if net_ok and not geo_fail:
            tips.append("当前距出发超出预报窗口，暂无逐日数据；请在出发前约 16 天内再次运行本脚本。")
        else:
            tips.append("天气服务暂时不可达，本次未取到预报数据；请稍后重跑本脚本，或出发前 1–2 天再查。")

    # 全程都落在窗口内的最早查询日 = 行程末日 -（窗口天数 - 1）
    full_window_from = end_date - timedelta(days=MAX_LEAD_DAYS - 1)
    if full_window_from > today:
        tips.append(
            f"行程末日 {end_date.isoformat()} 将在 {full_window_from.isoformat()} 进入 16 天预报窗口；"
            f"那天起再查一次即可拿到全程逐日预报（在此之前末尾的日子只会显示「临近再查」）。"
        )

    # ---- 渲染 HTML ----
    body = []
    for c in cards:
        if c["available"]:
            body.append(
                f"""
      <div class="card">
        <div class="date">Day {c['day']} · {c['date']} {c['weekday']}</div>
        <div class="places">{esc('、'.join(c['places'])) if c['places'] else ''}</div>
        <div class="weather">
          <span class="emoji">{c['emoji']}</span>
          <span class="desc">{esc(c['desc'])}</span>
        </div>
        <div class="nums">
          <span>🌡️ {c['tmin']}° ~ {c['tmax']}°C</span>
          <span>💧 降水 {c['rain']}%</span>
          <span>💨 风 {c['wind']} km/h</span>
        </div>
        <div class="stationline">数据取站：{esc(c['station']) or '—'}{'　（当日多站点温差较大，温度为各站区间）' if c['multi'] else ''}</div>
      </div>"""
            )
        else:
            body.append(
                f"""
      <div class="card nodata">
        <div class="date">Day {c['day']} · {c['date']} {c['weekday']}</div>
        <div class="places">{esc('、'.join(c['places'])) if c['places'] else ''}</div>
        <div class="weather"><span class="desc muted">临近再查（超出预报窗口）</span></div>
      </div>"""
            )

    tips_html = "\n".join(f"<li>{esc(t)}</li>" for t in tips)

    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} · 天气预报</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
         background:#f5f7fa; color:#1f2933; margin:0; padding:32px; }}
  .page {{ max-width:820px; margin:0 auto; background:#fff; border-radius:14px;
          box-shadow:0 2px 12px rgba(0,0,0,.08); padding:28px 32px; }}
  h1 {{ font-size:22px; margin:0 0 4px; }}
  .sub {{ color:#66727f; font-size:13px; margin-bottom:18px; }}
  .card {{ border:1px solid #e3e8ef; border-radius:10px; padding:14px 16px; margin:10px 0; }}
  .card.nodata {{ background:#fafbfc; }}
  .date {{ font-weight:600; font-size:14px; }}
  .places {{ color:#52606d; font-size:13px; margin:2px 0 8px; }}
  .stationline {{ color:#7b8794; font-size:12px; margin-top:8px; }}
  .weather {{ display:flex; align-items:center; gap:10px; font-size:18px; }}
  .emoji {{ font-size:30px; }}
  .desc.muted {{ color:#9aa5b1; font-size:14px; }}
  .nums {{ display:flex; gap:18px; margin-top:8px; color:#3e4c59; font-size:14px; flex-wrap:wrap; }}
  .tips {{ background:#eef5ff; border-left:4px solid #3b82f6; border-radius:8px;
          padding:12px 16px; margin-top:18px; }}
  .tips h2 {{ font-size:15px; margin:0 0 8px; }}
  .tips ul {{ margin:0; padding-left:20px; }}
  .tips li {{ margin:4px 0; font-size:14px; }}
  .foot {{ color:#9aa5b1; font-size:12px; margin-top:20px; }}
  @media print {{ body {{ background:#fff; padding:0; }} .page {{ box-shadow:none; }} }}
</style></head>
<body><div class="page">
  <h1>{esc(title)} · 天气预报</h1>
  <div class="sub">{esc(destination)} ｜ 出发 {start_date.isoformat()} ｜ 共 {days} 天 ｜ 生成于 {today.isoformat()}</div>
  {''.join(body)}
  <div class="tips"><h2>出行提示</h2><ul>{tips_html}</ul></div>
  <div class="foot">数据来源：Open-Meteo（免密钥实时预报）。天气随时间更新，出发前 1–2 天请再看一次。</div>
</div></body></html>"""

    import os

    os.makedirs(args.out, exist_ok=True)
    out_path = os.path.join(args.out, "weather.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    # 终端简报
    print("===== 天气简报 =====")
    if net_ok and any_data:
        for c in cards:
            if c["available"]:
                print(
                    f"  Day{c['day']} {c['date']} {c['weekday']} {c['desc']} "
                    f"{c['tmin']}~{c['tmax']}°C 降水{c['rain']}% 风{c['wind']}km/h"
                    + (f"  [取站 {c['station']}{'，多站区间' if c['multi'] else ''}]" if c.get("station") else "")
                )
    else:
        reason = "天气服务不可达，未取到数据" if (not net_ok or geo_fail) else "超出预报窗口，暂无数据"
        print(f"  （{reason}）")
    for t in tips:
        print("  · " + t)
    print(f"→ 已生成 {out_path}")
    if not net_ok or geo_fail:
        print("⚠️ 部分预报获取失败，请检查网络后重跑；已渲染可用页面，不阻断交付。")


if __name__ == "__main__":
    main()
