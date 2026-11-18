#!/usr/bin/env python3
"""读取 itinerary.json，生成可缩放地图 HTML 与带文字行程的路线图片 PNG，并做「出图前自检」。

用法:
    python3 generate_travel.py <itinerary.json> [--out <目录>] [--no-png] [--skip-verify]
                               [--geocode-only] [--dump-coords]

- 站点缺 lat/lng 时按顺序解析坐标：本地缓存 references/poi-coords.json → Photon → Nominatim（均为 WGS-84）。
- stop 带 coord_source: "gcj02" 时（腾讯/高德/百度取来的坐标）先自动换算成 WGS-84，避免标记偏 300~600m。
- --geocode-only：只解析坐标并打印「站点坐标核对表」后退出（有缺失/低置信返回码 2），便于先核对再出图。
- --dump-coords：输出可粘贴进 references/poi-coords.json 的坐标片段。
- HTML 用 Leaflet + OpenStreetMap（浏览器直接打开即可缩放/拖动）。
- PNG 用 Playwright 截图（需 pip install playwright；优先复用系统 Chrome）。
- 自检：HTML 无占位符残留/无 JS 错误/行程与标记齐全/地图瓦片加载；PNG 无截断且尺寸正常。
  任一关键项失败会以退出码 1 中止，提醒「不要交付，先排查」。
"""
import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from math import sin, cos, pi
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from coord_convert import gcj_to_wgs  # noqa: E402

DAY_COLORS = [
    "#e63946", "#f4a261", "#2a9d8f", "#4361ee", "#7209b7",
    "#f72585", "#fb8500", "#06d6a0", "#118ab2", "#8338ec",
]

UA = "travel-planner/1.0 (WorkBuddy)"
MAX_PNG_HEIGHT = 6000  # PNG 高度安全上限，超过则阻断并建议拆分行程

# 底图源：国内用高德（中文路网全、可达性好，需 GCJ-02 坐标），境外用 OSM（WGS-84）
BASEMAPS = {
    "amap": {
        "id": "amap",
        "url": "https://wprd0{s}.is.autonavi.com/appmaptile?x={x}&y={y}&z={z}&lang=zh_cn&size=1&scl=1&style=7",
        "subdomains": "1234",
        "attribution": "© 高德地图",
    },
    "osm": {
        "id": "osm",
        "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "subdomains": "abc",
        "attribution": "© OpenStreetMap",
    },
    "carto": {
        "id": "carto",
        "url": "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
        "subdomains": "abcd",
        "attribution": "© CARTO / OpenStreetMap",
    },
    # Esri 地形晕渲：纯地形、零标注，配合本页自带的常驻中文景点标签，可出「复古探险地图」风。
    # 用 WGS-84（与 OSM 同坐标系），国内/境外都可达（实测 200）。
    "esri_physical": {
        "id": "esri_physical",
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Physical_Map/MapServer/tile/{z}/{y}/{x}",
        "subdomains": "",
        "attribution": "© Esri, NASA, USGS",
    },
}


def in_china(lng, lat):
    """粗略判断坐标是否在中国大陆范围内（决定是否施加 GCJ-02 偏移）。"""
    return 72.0 <= lng <= 137.9 and 0.83 <= lat <= 53.9


def _fetch_json(url, tries=3, timeout=8):
    """带退避重试的 JSON 请求。Photon 偶发 SSL: UNEXPECTED_EOF 属瞬时错误，重试通常能过。"""
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            last = e
            if i < tries - 1:
                time.sleep(0.8 * (i + 1))
    raise last


PROVINCE_HINTS = ("黑龙江", "内蒙古", "新疆", "西藏", "广西", "宁夏", "云南", "四川", "山西", "山东",
                  "贵州", "广东", "浙江", "江苏", "福建", "湖南", "湖北", "河南", "河北", "陕西",
                  "甘肃", "青海", "海南", "吉林", "辽宁", "安徽", "江西", "台湾",
                  "北京", "上海", "天津", "重庆", "香港", "澳门")
# Photon 有时用 ISO-3166-2 代码表示省份（如「西湖」命中 state=ZJ 而非「浙江省」），需能对上
PROVINCE_ISO = {
    "北京": "BJ", "天津": "TJ", "上海": "SH", "重庆": "CQ", "河北": "HE", "山西": "SX",
    "辽宁": "LN", "吉林": "JL", "黑龙江": "HL", "江苏": "JS", "浙江": "ZJ", "安徽": "AH",
    "福建": "FJ", "江西": "JX", "山东": "SD", "河南": "HA", "湖北": "HB", "湖南": "HN",
    "广东": "GD", "海南": "HI", "四川": "SC", "贵州": "GZ", "云南": "YN", "陕西": "SN",
    "甘肃": "GS", "青海": "QH", "台湾": "TW", "内蒙古": "NM", "广西": "GX", "西藏": "XZ",
    "宁夏": "NX", "新疆": "XJ", "香港": "HK", "澳门": "MO",
}


def _province_ok(prov_tok, admin_blob):
    """省级归属校验：中文省名或 ISO 代码命中任一即可。"""
    if not prov_tok or not admin_blob:
        return True
    if prov_tok in admin_blob:
        return True
    code = PROVINCE_ISO.get(prov_tok)
    if not code:
        return False
    return code in re.split(r"[\s,，/|]+", admin_blob.upper())


def _ctx_tokens(ctx):
    """把 region/destination 拆成省/市/县多级 token（只用于归属校验，不拼进查询词）。

    region 常写成连续中文（「云南普洱思茅」「山西运城新绛」），因此：
    按分隔符拆 → 剥掉省名前缀 → 再按 2 字切分成可匹配的短 token。
    """
    if not ctx:
        return []
    parts = []
    for part in re.split(r"[\s,，、·/|]+", ctx.strip()):
        if len(part) < 2:
            continue
        for p in PROVINCE_HINTS:
            if part.startswith(p) and len(part) > len(p):
                parts.extend([p, part[len(p):]])
                break
        else:
            parts.append(part)
    toks = []
    for part in parts:
        toks.extend([part[i:i + 2] for i in range(0, len(part) - 1, 2)] if len(part) > 2 else [part])
    seen, uniq = set(), []
    for t in toks:
        if len(t) >= 2 and t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


NAME_PREFIXES = ("中国科学院", "中科院", "国家级", "国家")
NAME_SUFFIXES = ("国家森林公园", "国家公园", "森林公园", "风景名胜区", "风景区", "旅游景区",
                 "旅游小镇", "度假酒店", "景区", "公园", "古城", "酒店", "小镇", "庄园")
# 景区/园区/建筑类地名必须命中「场所」，不能是树、河、小径等同名自然物或线性物
FACILITY_KEYWORDS = ("景区", "公园", "庄园", "古城", "酒店", "民宿", "机场", "车站", "乐园",
                     "小镇", "博物馆", "口岸", "寺", "宫", "度假", "营地", "大学", "医院")
# 任何行程站点都不该落在「一棵树 / 一条小径」上：这类命中一律拒绝
ALWAYS_NON_PLACE_VALUES = {"tree", "scrub", "wood", "path", "track", "footway", "cycleway"}
# 景区/园区/建筑类地名必须命中「场所」，不能是河湖林草等自然物（「南腊河」这类没带场所词，不受此限）
FACILITY_NON_PLACE_VALUES = ALWAYS_NON_PLACE_VALUES | {
    "river", "stream", "water", "wetland", "grassland", "heath"}
# 行政标签点（边界/形心）：如「勐腊县」的 county 形心离县城 20km，仅作兜底
ADMIN_LABEL_VALUES = {"county", "state", "province", "region", "district", "administrative"}
# 聚落级：优先于标签点与车站等附属设施
SETTLEMENT_VALUES = {"city", "town", "village", "hamlet", "quarter", "neighbourhood", "suburb", "locality"}
# 「县城/城区」在地名库里通常落在「XX镇/XX街道」节点上
ADMIN_SUFFIX_MAP = (("县城", "镇"), ("城区", "街道"), ("市区", "市"))


def _core_name(name):
    """去掉机构前缀与通用后缀，得到核心地名（望天树景区→望天树）。"""
    core = name
    for _ in range(3):
        changed = False
        for pre in NAME_PREFIXES:
            if core.startswith(pre) and len(core) > len(pre) + 2:
                core, changed = core[len(pre):], True
        for suf in NAME_SUFFIXES:
            if core.endswith(suf) and len(core) > len(suf) + 2:
                core, changed = core[: -len(suf)], True
        if not changed:
            break
    return core


def _query_variants(name, ctx):
    """构造查询词链。

    实测（西双版纳/普洱 13 个站点）：Photon 的 q 一旦拼上「地名前缀」就很容易返回 0 条
    （「云南勐腊 勐腊县城」=0 条，「勐腊县城」=1 条），所以**纯地名优先**，加大地点前缀只作兜底。
    """
    core = _core_name(name)
    outs = [name]
    if core != name:
        outs.append(core)
    base = core if core != name else name
    for suf, rep in ADMIN_SUFFIX_MAP:
        if base.endswith(suf) and len(base) > len(suf):
            outs.append(base[: -len(suf)] + rep)
    # 去掉「城市/地区前缀」：Photon 对整串中文地名（如「杭州西湖」「普洱茶马古城」）召回为 0，
    # 拆出景点名（西湖 / 茶马古城）才能命中
    admin_only = {"县城", "城区", "市区", "老城", "城关"}
    for t in _ctx_tokens(ctx):
        for b in (name, core):
            rest = b[len(t):] if b.startswith(t) else ""
            if len(rest) >= 2 and rest not in admin_only:
                outs.append(rest)
    # 加大地点前缀（正例：「西双版纳嘎洒国际机场」可召回，「嘎洒国际机场」不可）
    for t in _ctx_tokens(ctx)[:3]:
        for b in list(outs):
            if t not in b:
                outs.append(t + b)
    seen, uniq = set(), []
    for q in outs:
        if q and len(q) >= 2 and q not in seen:
            seen.add(q)
            uniq.append(q)
    return uniq[:6]


def _score_features(feats, name, core, toks):
    """打分 + 硬性过滤。返回 [(score, feature, meta)]，按分数降序。"""
    scored = []
    facility = any(k in name for k in FACILITY_KEYWORDS)
    for f in feats:
        p = f.get("properties") or {}
        vals = {k: str(p.get(k) or "") for k in
                ("state", "city", "county", "district", "locality", "name", "street")}
        fname = vals["name"]
        osm_value = str(p.get("osm_value") or "")
        if not fname:
            continue
        blob = " ".join(vals.values())
        admin_blob = " ".join(v for k, v in vals.items()
                              if k in ("state", "city", "county", "district", "locality") and v)
        # 硬校验 1：有行政字段时，省级归属必须能对上（挡掉跨省同名，如「小熊猫庄园」命中成都的小熊猫园）；
        #           完全没有行政字段时（Photon 常见）无法校验，放行但降为低置信
        if not _province_ok(toks[0] if toks else "", admin_blob):
            continue
        # 硬校验 2：名称必须有重叠（挡掉「普洱茶马古城」命中昭通的「普洱镇」）
        if not (fname in name or fname in core or (core and core in fname)):
            continue
        # 硬校验 3：拒绝「树 / 小径」这类非场所命中（如「望天树景区」命中植物园里的望天树[tree]）；
        #           带场所词（景区/公园/机场…）的地名再额外拒绝河湖林草
        if osm_value in ALWAYS_NON_PLACE_VALUES:
            continue
        if facility and osm_value in FACILITY_NON_PLACE_VALUES:
            continue

        if admin_blob and len(toks) >= 2:
            loc_ok = any(t in admin_blob for t in toks[1:])
        elif not admin_blob:
            loc_ok = False  # 无行政字段可校验，交给人工确认
        else:
            loc_ok = True
        score = 3 if loc_ok and len(toks) >= 2 else 0
        score += 2 if fname == name else (1 if core and core in fname else 0)
        if osm_value in SETTLEMENT_VALUES:
            score += 2
        elif osm_value in ADMIN_LABEL_VALUES:
            score -= 1
        if p.get("type") in ("city", "district", "locality"):
            score += 1
        scored.append((score, f, {
            "loc_ok": loc_ok,
            "osm": f"{p.get('osm_key')}={osm_value}",
            "admin": " / ".join(v for v in (vals["state"], vals["city"], vals["county"]) if v),
        }))
    scored.sort(key=lambda t: -t[0])
    return scored


def _geocode_photon(name, ctx):
    """Photon 解析为 WGS-84。返回 (lat, lng, meta)；失败返回 (None, None, meta)。"""
    toks = _ctx_tokens(ctx)
    core = _core_name(name)
    tried = []
    for q in _query_variants(name, ctx):
        url = "https://photon.komoot.io/api/?" + urllib.parse.urlencode({"q": q, "limit": 5})
        try:
            data = _fetch_json(url)
        except Exception as e:  # noqa: BLE001
            print(f"  [warn] Photon 请求失败: {q} ({e})", file=sys.stderr)
            continue
        scored = _score_features(data.get("features") or [], name, core, toks)
        if not scored:
            tried.append(q)
            continue
        score, feat, meta = scored[0]
        coords = feat["geometry"]["coordinates"]  # [lng, lat]
        alts = [f"{round(x[1]['geometry']['coordinates'][1], 4)},{round(x[1]['geometry']['coordinates'][0], 4)}"
                for x in scored[1:3]]
        meta.update({
            "via": "photon",
            "query": q,
            "conf": "ok" if (meta["loc_ok"] and score >= 3) else "low",
            "alt": alts,
        })
        return float(coords[1]), float(coords[0]), meta
    return None, None, {"via": "photon", "tried": tried}


def _geocode_nominatim(name, ctx):
    """Nominatim(OSM) 兜底。无归属校验，一律标低置信。返回 (lat, lng, meta)。"""
    q = f"{name}, {ctx}" if ctx else name
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"format": "json", "q": q, "limit": 1, "accept-language": "zh-CN"}
    )
    try:
        data = _fetch_json(url, tries=2, timeout=10)
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"]), {
                "via": "nominatim", "query": q, "conf": "low", "loc_ok": True, "osm": "nominatim", "admin": ""}
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] Nominatim 编码失败: {name} ({e})", file=sys.stderr)
    return None, None, None


def geocode(name, ctx):
    """Photon 优先，失败再试 Nominatim。返回 (lat, lng, meta)；全失败为 (None, None, meta)。"""
    lat, lng, meta = _geocode_photon(name, ctx)
    if lat is not None:
        return lat, lng, meta
    lat, lng, nm = _geocode_nominatim(name, ctx)
    if lat is not None:
        return lat, lng, nm
    return None, None, (meta or {"via": "photon"})


CACHE_PATH = Path(__file__).resolve().parent.parent / "references" / "poi-coords.json"


def load_coord_cache():
    """读取已核实 POI 坐标缓存（references/poi-coords.json）。缺失时返回空字典。"""
    try:
        raw = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return {k: v for k, v in raw.items()
            if not k.startswith("_") and isinstance(v, dict)
            and v.get("lat") is not None and v.get("lng") is not None}


def cache_lookup(cache, name):
    """先精确匹配，再退化为「缓存键是站点名子串」的模糊匹配（取最长键）。"""
    if name in cache:
        return cache[name]
    cands = [k for k in cache if k and k in name]
    return cache[max(cands, key=len)] if cands else None


def straight_km(lat1, lng1, lat2, lng2):
    """两点直线距离（km），用于核对表里的「距上一站」提示。"""
    dy = (lat2 - lat1) * 111.32
    dx = (lng2 - lng1) * 111.32 * cos((lat1 + lat2) / 2 * pi / 180)
    return (dx * dx + dy * dy) ** 0.5


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>__TITLE__</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<style>
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; color: #1f2933; }
  .wrap { display: flex; height: 100vh; }
  .sidebar { width: 380px; flex: 0 0 380px; overflow-y: auto; padding: 22px 18px; background: #f7f9fc; border-right: 1px solid #e4e9f0; }
  .sidebar h1 { font-size: 21px; margin: 0 0 6px; }
  .meta { font-size: 12px; color: #5b6b7c; margin-bottom: 16px; line-height: 1.7; }
  .tools { display: flex; gap: 8px; margin-bottom: 12px; }
  .tbtn { font-size: 12px; padding: 4px 10px; border: 1px solid #cdd6e0; background: #fff; border-radius: 6px; cursor: pointer; color: #3a4a5a; }
  .tbtn:hover { background: #eef3fb; }
  .day { border-radius: 10px; background: #fff; padding: 10px 12px; margin-bottom: 10px; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
  .day h2 { font-size: 14px; margin: 0 0 8px; display: flex; align-items: center; gap: 8px; cursor: pointer; user-select: none; justify-content: space-between; }
  .day .chev { font-size: 12px; color: #8a97a5; transition: transform .15s; }
  .day.collapsed .chev { transform: rotate(-90deg); }
  .day .day-body { margin-top: 2px; }
  .day.collapsed .day-body { display: none; }
  .dot { width: 18px; height: 18px; border-radius: 50%; color: #fff; font-size: 11px; display: inline-flex; align-items: center; justify-content: center; font-weight: 700; }
  .stop { font-size: 13px; padding: 5px 0; border-top: 1px dashed #eef1f5; cursor: pointer; transition: background .15s; }
  .stop:hover { background: #eef3fb; }
  .stop.active { background: #dbeafe; }
  .stop:first-of-type { border-top: none; }
  .stop .t { color: #8a97a5; font-variant-numeric: tabular-nums; margin-right: 6px; }
  .stop .n { font-weight: 600; }
  .stop .note { color: #6b7886; font-size: 12px; display: block; margin-top: 2px; }
  #map { flex: 1; height: 100vh; }
  .leaflet-popup-content { font-size: 13px; }
  .pop-title { font-weight: 700; margin-bottom: 2px; }
  .pop-note { color: #6b7886; }
  /* 常驻名称标签：每个数字标记旁直接显示景点名 */
  .mlabel { background: #fff; border: 1px solid #cdd6e0; border-radius: 6px; padding: 1px 6px;
            font-size: 11px; color: #1f2933; box-shadow: 0 1px 3px rgba(0,0,0,.15); white-space: nowrap; }
  .mlabel::before { display: none; }  /* 去掉 tooltip 默认小三角 */

  /* ============ 风格化主题（去商务感） ============ */
  /* 去掉 divIcon 默认白底方块 */
  .leaflet-div-icon { background: transparent; border: none; }
  :root {
    --hand-font: "HanziPen SC","Hannotate SC","STKaiti","楷体-简","KaiTi","华文楷体",sans-serif;
    --paper: #fbf3e4; --ink: #5a4326;
  }
  /* 路线标记：基础为水滴 pin，颜色由 --mk-bg（按天色）注入，形状随主题覆盖 */
  .route-marker {
    background: var(--mk-bg); width: 28px; height: 28px;
    border-radius: 50% 50% 50% 0; transform: rotate(-45deg);
    border: 2px solid #fff; box-shadow: 0 1px 3px rgba(0,0,0,.4);
    display: flex; align-items: center; justify-content: center;
  }
  .route-marker span { transform: rotate(45deg); color: #fff; font-size: 12px; font-weight: 700; }

  /* 风格切换器 */
  .style-switch { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-bottom: 14px; }
  .style-switch .ss-label { font-size: 12px; color: #8a97a5; margin-right: 2px; }
  .style-switch button { font-size: 12px; padding: 4px 10px; border: 1px solid #cdd6e0;
    background: #fff; border-radius: 14px; cursor: pointer; color: #3a4a5a; }
  .style-switch button.active { background: #4361ee; color: #fff; border-color: #4361ee; }

  /* —— 清新水彩手账 —— */
  body.theme-watercolor { background: #f7efe0; }
  body.theme-watercolor .leaflet-tile-pane { filter: sepia(.30) saturate(.92) brightness(1.05) contrast(.94); }
  body.theme-watercolor .sidebar { background: var(--paper); border-right: 1px solid #e7d9bf; }
  body.theme-watercolor .sidebar h1 { font-family: var(--hand-font); color: #6b4f2a; }
  body.theme-watercolor .meta { color: #8a6f4a; }
  body.theme-watercolor .day { background: #fffaf0; box-shadow: 0 1px 3px rgba(150,120,70,.18); }
  body.theme-watercolor .day h2 { color: #6b4f2a; }
  body.theme-watercolor .stop .n { font-family: var(--hand-font); }
  body.theme-watercolor .route-marker { transform: rotate(-45deg) scale(1.08); }
  body.theme-watercolor .route-marker span { font-family: var(--hand-font); }
  body.theme-watercolor .leaflet-overlay-pane path.route-line { filter: url(#wobble); }
  body.theme-watercolor .mlabel { background:#fffdf7; color:#5a4326; border:1px solid #d8c39a; font-family:var(--hand-font); }

  /* —— 复古探险地图 —— */
  body.theme-vintage { background: #ecdfc4; }
  body.theme-vintage .leaflet-tile-pane { filter: sepia(.12) contrast(1.03); }
  body.theme-vintage .sidebar { background: #f1e4c8; border-right: 1px solid #c9ad7a; }
  body.theme-vintage .sidebar h1 { font-family: var(--hand-font); color: #5a4326; }
  body.theme-vintage .meta { color: #7a6240; }
  body.theme-vintage .day { background: #f7eed6; box-shadow: 0 1px 3px rgba(120,90,40,.2); border: 1px solid #e0cda0; }
  body.theme-vintage .day h2 { color: #5a4326; }
  body.theme-vintage .route-marker { border-radius: 50%; border: 2.5px solid #6b4f2a;
    box-shadow: 0 1px 2px rgba(0,0,0,.3); transform: none; }
  body.theme-vintage .route-marker span { transform: none; font-family: var(--hand-font); }
  body.theme-vintage .leaflet-overlay-pane path.route-line { filter: url(#wobbleStrong); }
  body.theme-vintage .mlabel { background:#f5ecd6; color:#5a4326; border:1px solid #b8975a; font-family:var(--hand-font); }
  body.theme-vintage .style-switch button.active { background: #6b4f2a; border-color: #6b4f2a; }

  /* —— 日系简笔贴纸 —— */
  body.theme-sticker { background: #fbfbf9; }
  body.theme-sticker .leaflet-tile-pane { filter: grayscale(.35) brightness(1.07) contrast(.96); }
  body.theme-sticker .sidebar { background: #fff; border-right: 1px solid #ececec; }
  body.theme-sticker .sidebar h1 { font-family: var(--hand-font); color: #444; }
  body.theme-sticker .day { background: #fff; }
  body.theme-sticker .route-marker { border-radius: 14px; border: 2px dashed #fff; box-shadow: 0 2px 5px rgba(0,0,0,.18); }
  body.theme-sticker .route-marker span { font-family: var(--hand-font); }
  body.theme-sticker .leaflet-overlay-pane path.route-line { filter: url(#wobble); }
  body.theme-sticker .mlabel { background:#fff; color:#444; border:2px dashed #c9c2b6; font-family:var(--hand-font); }
  body.theme-sticker .style-switch button.active { background: #118ab2; border-color: #118ab2; }

  /* —— 原版（默认导航风，无滤镜） —— */
  body.theme-original .style-switch button.active { background: #4361ee; border-color: #4361ee; }

  /* 插画（AI 手绘风，按文件名自动匹配；缺失则自动隐藏，不影响排版） */
  .cover { width: 100%; border-radius: 10px; margin-bottom: 14px; display: block;
    box-shadow: 0 2px 8px rgba(0,0,0,.12); }
  .stop-thumb { width: 100%; height: auto; border-radius: 8px; margin-top: 6px; display: block;
    box-shadow: 0 1px 4px rgba(0,0,0,.1); }
</style>
</head>
<body>
<div class="wrap">
  <svg width="0" height="0" style="position:absolute"><defs>
    <filter id="wobble"><feTurbulence type="turbulence" baseFrequency="0.012" numOctaves="2" seed="7" result="n"/>
      <feDisplacementMap in="SourceGraphic" in2="n" scale="4" xChannelSelector="R" yChannelSelector="G"/></filter>
    <filter id="wobbleStrong"><feTurbulence type="fractalNoise" baseFrequency="0.02" numOctaves="2" seed="3" result="n"/>
      <feDisplacementMap in="SourceGraphic" in2="n" scale="6"/></filter>
  </defs></svg>
  <aside class="sidebar" id="sidebar"></aside>
  <div id="map"></div>
</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
var ITIN = __DATA__;
var DAYCOLORS = __DAYCOLORS__;
// 点击左侧站点时地图飞行到的缩放级别（可在 itinerary.json 的 trip.click_zoom 调整，默认 14）
var CLICK_ZOOM = (ITIN.trip && ITIN.trip.click_zoom) ? Number(ITIN.trip.click_zoom) : 14;
function esc(t){ return (t==null?'':String(t)).replace(/[&<>"]/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }

// ---- 左侧文字行程（纯 DOM） ----
var trip = ITIN.trip || {};
var stops = (ITIN.stops || []).map(function(s){ if(s.day!=null) s.day = parseInt(s.day,10); return s; });
// 每个站点绑定原始索引，供左侧点击与地图标记互相联动
var markersByIdx = {};
stops.forEach(function(s,i){ s.__i = i; });
var sb = document.getElementById('sidebar');
// 封面插画（illustrations/cover.png，缺失自动隐藏，不阻断排版）
var cover = document.createElement('img');
cover.className = 'cover'; cover.src = 'illustrations/cover.png'; cover.alt = '封面插画';
cover.onerror = function(){ cover.style.display = 'none'; };
sb.appendChild(cover);
// 风格切换器（水彩手账 / 复古探险 / 简笔贴纸 / 原版），选择记 localStorage
var ss = document.createElement('div'); ss.className = 'style-switch'; ss.id = 'styleSwitch';
ss.innerHTML = '<span class="ss-label">风格</span>'
  + '<button data-theme="watercolor">水彩手账</button>'
  + '<button data-theme="vintage">复古探险</button>'
  + '<button data-theme="sticker">简笔贴纸</button>'
  + '<button data-theme="original">原版</button>';
ss.addEventListener('click', function(e){
  var t = e.target.getAttribute && e.target.getAttribute('data-theme');
  if (t) applyTheme(t);
});
sb.appendChild(ss);
var h1 = document.createElement('h1'); h1.textContent = trip.title || '旅行行程'; sb.appendChild(h1);
var meta = document.createElement('div'); meta.className = 'meta';
meta.innerHTML = [trip.destination, trip.start_date, trip.days ? trip.days+'天' : '', trip.travelers, trip.budget, trip.theme]
  .filter(Boolean).map(esc).join(' · ');
sb.appendChild(meta);
// 折叠工具条：全部展开 / 全部折叠
var tools = document.createElement('div'); tools.className = 'tools';
var btnAll = document.createElement('button'); btnAll.textContent = '全部展开'; btnAll.className = 'tbtn';
btnAll.onclick = function(){ document.querySelectorAll('#sidebar .day').forEach(function(x){ x.classList.remove('collapsed'); }); };
var btnNone = document.createElement('button'); btnNone.textContent = '全部折叠'; btnNone.className = 'tbtn';
btnNone.onclick = function(){ document.querySelectorAll('#sidebar .day').forEach(function(x){ x.classList.add('collapsed'); }); };
tools.appendChild(btnAll); tools.appendChild(btnNone); sb.appendChild(tools);
var byDay = {};
stops.forEach(function(s){ (byDay[s.day] = byDay[s.day] || []).push(s); });
var COLLAPSED = (ITIN.trip && ITIN.trip.collapsed_days) || [];  // 默认折叠的天（数组，如 [3]）
Object.keys(byDay).map(Number).sort(function(a,b){ return a-b; }).forEach(function(d){
  var sec = document.createElement('div'); sec.className = 'day';
  if (COLLAPSED.indexOf(d) >= 0) sec.classList.add('collapsed');
  var h2 = document.createElement('h2');
  var dot = document.createElement('span'); dot.className = 'dot'; dot.style.background = DAYCOLORS[d] || '#4361ee'; dot.textContent = d;
  h2.appendChild(dot); h2.appendChild(document.createTextNode(' 第'+d+'天'));
  var chev = document.createElement('span'); chev.className = 'chev'; chev.textContent = '▾'; h2.appendChild(chev);
  sec.appendChild(h2);
  var body = document.createElement('div'); body.className = 'day-body';
  byDay[d].forEach(function(s){
    var el = document.createElement('div'); el.className = 'stop';
    el.dataset.idx = s.__i;
    el.addEventListener('click', function(){ focusStop(s.__i); });
    var html = '<span class="t">'+(s.time||'')+'</span><span class="n">'+esc(s.name)+'</span>';
    if (s.note) html += '<span class="note">'+esc(s.note)+'</span>';
    el.innerHTML = html; body.appendChild(el);
    // 每站手绘插画缩略图（按站名匹配 illustrations/<站名>.png，缺失自动隐藏）
    var thumb = document.createElement('img');
    thumb.className = 'stop-thumb';
    thumb.src = 'illustrations/' + encodeURIComponent(s.name) + '.png';
    thumb.alt = s.name;
    thumb.onerror = function(){ thumb.style.display = 'none'; };
    el.appendChild(thumb);
  });
  sec.appendChild(body);
  // 折叠/展开：点击当天标题切换，箭头同步
  h2.addEventListener('click', function(){ sec.classList.toggle('collapsed'); });
  sb.appendChild(sec);
});

// ---- 地图：底图按行程范围自动选择（国内高德 / 境外 OSM），可在 trip.basemap 覆盖 ----
var map = L.map('map', { zoomControl: true });
var BASEMAPS = __BASEMAPS__;
var routeLayer = L.layerGroup().addTo(map);
var tileLayer = null;
var basemapIndex = 0;
var pts = [];

// 高德底图用 GCJ-02 坐标，OSM/CARTO 用原始 WGS-84
function coordOf(s){
  if (BASEMAPS[basemapIndex].id === 'amap' && s.lat_gcj != null && s.lng_gcj != null) {
    return [s.lat_gcj, s.lng_gcj];
  }
  return [s.lat, s.lng];
}
function applyBasemap(i){
  if (tileLayer) map.removeLayer(tileLayer);
  basemapIndex = i;
  var b = BASEMAPS[i];
  tileLayer = L.tileLayer(b.url, { subdomains: b.subdomains || 'abc', maxZoom: 19, attribution: b.attribution || '' }).addTo(map);
}
function draw(){
  routeLayer.clearLayers();
  markersByIdx = {};
  pts = [];
  var prev = null;
  stops.forEach(function(s){
    if (s.lat == null || s.lng == null) return;
    var ll = coordOf(s); pts.push(ll);
    var color = DAYCOLORS[s.day] || '#4361ee';
    var icon = L.divIcon({ className: 'route-marker-wrap', html:
      '<div class="route-marker" style="--mk-bg:'+color+'"><span>'+s.day+'</span></div>',
      iconSize: [28,28], iconAnchor: [14,28] });
    var popup = '<div class="pop-title">第'+s.day+'天 '+(s.time||'')+' · '+esc(s.name)+'</div>'+(s.note?'<div class="pop-note">'+esc(s.note)+'</div>':'');
    var mk = L.marker(ll, { icon: icon }).addTo(routeLayer).bindPopup(popup);
    markersByIdx[s.__i] = mk;
    mk.on('click', function(){ highlightSidebar(s.__i); });  // 地图→左侧反联动
    // 常驻名称标签：每个数字标记旁直接显示景点名（无需点击）
    mk.bindTooltip(esc(s.name), { permanent: true, direction: 'right', offset: [10, 0], className: 'mlabel' });
    // 连续实线：按序连接所有站点（跨天也连），形成完整路线而非分段断线
    if (prev) L.polyline([prev, ll], { color: color, weight: 4, opacity: .85, className: 'route-line' }).addTo(routeLayer);
    prev = ll;
  });
  // 环线闭合：若首末站点同名（出发地=返程地），用虚线把终点连回起点
  if (pts.length > 2) {
    var fIdx = stops.findIndex(function(s){ return s.lat != null && s.lng != null; });
    var lIdx = -1;
    for (var i = stops.length - 1; i >= 0; i--) { if (stops[i].lat != null && stops[i].lng != null) { lIdx = i; break; } }
    if (fIdx >= 0 && lIdx >= 0 && stops[fIdx].name === stops[lIdx].name) {
      L.polyline([pts[pts.length - 1], pts[0]], { color: DAYCOLORS[stops[fIdx].day] || '#4361ee', weight: 4, opacity: .85, dashArray: '2,8', className: 'route-line' }).addTo(routeLayer);
    }
  }
  window.__PTS__ = pts;
  scheduleDeclutter();
}
function fitAll(){
  if (pts.length) map.fitBounds(pts, { padding: [40,40] }); else map.setView([35,105], 4);
}

// ---- 标签避让：常驻景点名重叠时按优先级微调偏移，不隐藏任何名字 ----
// 站点密集（如景洪机场↔傣族园、野象谷↔大渡岗）时，右侧标签会互相压住；
// 这里依次尝试「原位 → 上下/左右 → 左侧翻转」，选第一个不碰撞的位置。
var __declutterTimer = null;
function scheduleDeclutter(){ clearTimeout(__declutterTimer); __declutterTimer = setTimeout(declutterLabels, 60); }
function declutterLabels(){
  var mapEl = document.getElementById('map');
  if (!mapEl) return;
  var mr = mapEl.getBoundingClientRect();
  var els = Array.prototype.slice.call(document.querySelectorAll('.leaflet-tooltip.mlabel'));
  if (!els.length) return;
  // 先清空上一轮的偏移，再按原始位置重新测量（DOM 顺序 = 站点顺序 = 优先级）
  els.forEach(function(el){ el.style.marginLeft = ''; el.style.marginTop = ''; });
  var placed = [];
  els.forEach(function(el){
    var b = el.getBoundingClientRect();
    var w = b.width, h = b.height;
    var offs = [[0,0],[0,-(h+4)],[0,h+4],[-(w+18),0],[0,-(h*2+8)],[0,h*2+8],[-(w+18),-(h+4)],[-(w+18),h+4]];
    var pick = null;
    for (var i=0;i<offs.length;i++){
      var ox=offs[i][0], oy=offs[i][1];
      var r={left:b.left+ox, right:b.right+ox, top:b.top+oy, bottom:b.bottom+oy};
      // 不能超出地图可视区（用地图自身矩形，否则会被左侧栏遮住）
      if (r.left < mr.left+2 || r.right > mr.right-2 || r.top < mr.top+2 || r.bottom > mr.bottom-2) continue;
      var clash = false;
      for (var j=0;j<placed.length;j++){
        var p = placed[j];
        if (!(r.right < p.left-1 || r.left > p.right+1 || r.bottom < p.top-1 || r.top > p.bottom+1)) { clash = true; break; }
      }
      if (!clash) { pick = {ox:ox, oy:oy, r:r}; break; }
    }
    if (!pick) pick = {ox:0, oy:0, r:b};  // 实在避不开就保持原位，名字不丢
    if (pick.ox) el.style.marginLeft = pick.ox + 'px';
    if (pick.oy) el.style.marginTop = pick.oy + 'px';
    placed.push(pick.r);
  });
}
map.on('moveend zoomend viewreset', scheduleDeclutter);
window.addEventListener('resize', scheduleDeclutter);
window.__declutter__ = declutterLabels;
window.__setBasemap__ = function(i){ applyBasemap(i); draw(); fitAll(); };
window.__basemapId__ = function(){ return BASEMAPS[basemapIndex].id; };
// ---- 风格主题：定义与切换（去商务感，多风格可切换） ----
var THEME_DEFAULT_BM = '__DEF_BM__';
var THEMES = {
  original:   { bm: THEME_DEFAULT_BM },
  watercolor: { bm: THEME_DEFAULT_BM },
  sticker:    { bm: THEME_DEFAULT_BM },
  vintage:    { bm: 'esri_physical' }
};
function applyTheme(name){
  if (!THEMES[name]) name = 'original';
  document.body.className = 'theme-' + name;
  var cfg = THEMES[name];
  var idx = BASEMAPS.findIndex(function(b){ return b.id === cfg.bm; });
  if (idx < 0) idx = 0;
  if (BASEMAPS[basemapIndex].id !== cfg.bm) window.__setBasemap__(idx);
  try { localStorage.setItem('tripweaver-theme', name); } catch (e) {}
  var btns = document.querySelectorAll('#styleSwitch button');
  for (var i = 0; i < btns.length; i++) {
    btns[i].classList.toggle('active', btns[i].getAttribute('data-theme') === name);
  }
}
// 初始：读取上次选择（默认水彩手账）
var initialTheme = 'watercolor';
try { var _saved = localStorage.getItem('tripweaver-theme'); if (_saved) initialTheme = _saved; } catch (e) {}
var _initIdx = BASEMAPS.findIndex(function(b){ return b.id === THEMES[initialTheme].bm; });
if (_initIdx < 0) _initIdx = 0;
window.__setBasemap__(_initIdx);   // 设底图 + draw() + fitAll()
applyTheme(initialTheme);          // 设主题类 + 按钮高亮（底图已一致，不再重切）
// ---- 左→右联动：点击左侧站点，地图飞到对应标记并弹窗；右→左高亮反联动 ----
function focusStop(i){
  var mk = markersByIdx[i]; if (!mk) return;
  var ll = mk.getLatLng();
  map.flyTo(ll, Math.max(map.getZoom(), CLICK_ZOOM), { duration: 0.6 });
  mk.openPopup(); highlightSidebar(i);
}
function highlightSidebar(i){
  var els = document.querySelectorAll('#sidebar .stop');
  els.forEach(function(e){ e.classList.toggle('active', e.dataset.idx === String(i)); });
  var active = document.querySelector('#sidebar .stop.active');
  if (active) {
    var day = active.closest('.day');
    if (day && day.classList.contains('collapsed')) day.classList.remove('collapsed');  // 反联动时自动展开所在天
    active.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
}
// 暴露给自检脚本：便于 PNG 高度自适应时重新适配地图
window.__MAP__ = map;
window.__PTS__ = pts;
</script>
</body>
</html>
"""


# ---- WGS-84 -> GCJ-02（高德/腾讯底图坐标偏移，保证标记贴合国内路网） ----
_GCJ_A = 6378245.0
_GCJ_EE = 0.00669342162296594323


def _transform_lat(x, y):
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * (abs(x) ** 0.5)
    ret += (20.0 * sin(6.0 * x * pi) + 20.0 * sin(2.0 * x * pi)) * 2.0 / 3.0
    ret += (20.0 * sin(y * pi) + 40.0 * sin(y / 3.0 * pi)) * 2.0 / 3.0
    ret += (160.0 * sin(y / 12.0 * pi) + 320.0 * sin(y * pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(x, y):
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * (abs(x) ** 0.5)
    ret += (20.0 * sin(6.0 * x * pi) + 20.0 * sin(2.0 * x * pi)) * 2.0 / 3.0
    ret += (20.0 * sin(x * pi) + 40.0 * sin(x / 3.0 * pi)) * 2.0 / 3.0
    ret += (150.0 * sin(x / 12.0 * pi) + 300.0 * sin(x / 30.0 * pi)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lng, lat):
    # 境外坐标不做偏移：GCJ-02 偏移算法仅适用于中国大陆，境外施加会凭空产生数百米误差
    if not in_china(lng, lat):
        return lng, lat
    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * pi
    magic = sin(radlat)
    magic = 1 - _GCJ_EE * magic * magic
    sqrtmagic = magic ** 0.5
    dlat = (dlat * 180.0) / ((_GCJ_A * (1 - _GCJ_EE)) / (magic * sqrtmagic) * pi)
    dlng = (dlng * 180.0) / (_GCJ_A / sqrtmagic * cos(radlat) * pi)
    return lng + dlng, lat + dlat


def build_html(itin, basemap_ids):
    data_json = json.dumps(itin, ensure_ascii=False).replace("</", "<\\/")
    days = sorted({int(s["day"]) for s in itin.get("stops", []) if s.get("day") is not None})
    day_color = {d: DAY_COLORS[i % len(DAY_COLORS)] for i, d in enumerate(days)}
    title = (itin.get("trip", {}).get("title") or "旅行行程")
    basemaps = [BASEMAPS[b] for b in basemap_ids]
    return (HTML_TEMPLATE
            .replace("__DATA__", data_json)
            .replace("__DAYCOLORS__", json.dumps(day_color, ensure_ascii=False))
            .replace("__BASEMAPS__", json.dumps(basemaps, ensure_ascii=False))
            .replace("__DEF_BM__", basemap_ids[0])
            .replace("__TITLE__", title))


def resolve_basemaps(itin):
    """返回底图 id 列表（第一个为主底图，其余为备用回退）。
    国内行程 → 高德（中文路网全）；境外 → OSM。可用 trip.basemap 覆盖。"""
    override = (itin.get("trip", {}).get("basemap") or "").lower().strip()
    if override in BASEMAPS:
        return [override, "osm" if override != "osm" else "carto"]

    coords = [(s["lng"], s["lat"]) for s in itin.get("stops", [])
              if s.get("lat") is not None and s.get("lng") is not None]
    if not coords:
        return ["amap", "osm"]
    domestic = sum(1 for lng, lat in coords if in_china(lng, lat))
    if domestic >= len(coords) / 2:
        return ["amap", "osm"]
    return ["osm", "carto"]


def plan_basemaps(itin):
    """返回传入 HTML 的底图切换列表（含 esri_physical，供「复古探险」风格切换）。

    国内行程把高德放首位（中文路网全），境外把 OSM 放首位；esri_physical 始终在列表内，
    无论哪种风格都能在 amap/osm/esri 间自由切换。__setBasemap__ 的自动回退仍按列表顺序。
    """
    primary = resolve_basemaps(itin)[0]
    if primary == "amap":
        return ["amap", "esri_physical", "osm", "carto"]
    return ["osm", "carto", "esri_physical", "amap"]


def launch_browser(playwright):
    """优先复用系统已安装的浏览器做渲染，避免下载 playwright chromium（数百 MB、常很慢）：
    系统 Chrome → 系统 Edge → playwright 自带 chromium。
    返回 (browser, 引擎名)。"""
    attempts = [
        ({"channel": "chrome"}, "系统 Chrome"),
        ({"channel": "msedge"}, "系统 Edge"),
        ({}, "playwright Chromium"),
    ]
    last_err = None
    for kwargs, label in attempts:
        try:
            return playwright.chromium.launch(**kwargs), label
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise RuntimeError(f"系统 Chrome / Edge 与内置 Chromium 均无法启动：{last_err}")


def verify_and_render(html_path, png_path, itin, want_png, basemap_count=1):
    """启动一次 Playwright 会话：渲染 PNG（自适应高度防截断）+ 跑全套自检，返回 (ok, report_lines)。

    自检分级：
    - ❌ 阻断项：结构性错误（占位符残留 / 行程未渲染 / 站点数不符 / JS 报错 / PNG 截断）→ 退出码 1。
    - ⚠️ 降级项：环境类问题（无网络、缺 playwright、坐标缺失）→ 仅告警，仍允许交付。
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return True, ["⚠️ 未安装 playwright，跳过自检与 PNG（HTML 已生成，可直接交付）。"
                      "如需 PNG：pip install playwright（渲染优先复用系统 Chrome，无需 playwright install chromium）"]

    report = []
    ok = True
    errors = []

    with sync_playwright() as p:
        try:
            browser, engine = launch_browser(p)
        except Exception as e:  # noqa: BLE001
            return True, [f"⚠️ 无法启动浏览器（{e}），跳过自检与 PNG（HTML 已生成，可直接交付）。"
                          "安装 Google Chrome 或执行 playwright install chromium 后重跑即可出 PNG"]
        report.append(f"ℹ️ 渲染引擎: {engine}")
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.on("pageerror", lambda e: errors.append(str(e)))

        # 控制台错误分两类：
        #   - 真实 JS 异常（pageerror 与 console.error 的非资源类）→ 阻断
        #   - 资源 404（如尚未生成的插画 illustrations/<站名>.png）→ 由 onerror 优雅隐藏，
        #     属预期，不计入致命错误，否则会误伤「未给每个站点都配插画」的正常情况
        def _on_console(m):
            if m.type != "error":
                return
            txt = m.text
            if ("Failed to load resource" in txt or "ERR_FILE_NOT_FOUND" in txt
                    or txt.startswith("net::") or "ERR_" in txt):
                return
            errors.append(f"console.error: {txt}")
        page.on("console", _on_console)
        page.goto("file://" + str(html_path))
        try:
            page.wait_for_load_state("networkidle", timeout=8000)  # 等瓦片基本加载完
        except Exception:
            pass
        page.wait_for_timeout(1500)  # 缓冲，确保瓦片铺满再截图

        # ---------- HTML 自检 ----------
        html_text = html_path.read_text(encoding="utf-8")
        for ph in ("__DATA__", "__DAYCOLORS__", "__TITLE__"):
            if ph in html_text:
                ok = False
                report.append(f"❌ HTML 含未替换占位符: {ph}")

        sb_blocks = page.evaluate("() => document.getElementById('sidebar').children.length")
        if sb_blocks < 2:
            ok = False
            report.append(f"❌ 左侧行程未渲染 (sidebar blocks={sb_blocks})")
        else:
            report.append(f"✅ 左侧行程渲染正常 (blocks={sb_blocks})")

        stop_count = page.evaluate("() => document.querySelectorAll('#sidebar .stop').length")
        expected_stops = len([s for s in itin.get("stops", []) if s.get("name")])
        if stop_count != expected_stops:
            ok = False
            report.append(f"❌ 站点数不符: HTML={stop_count} 期望={expected_stops}")
        else:
            report.append(f"✅ 站点数一致: {stop_count}")

        def tile_stats():
            loaded = page.evaluate("() => document.querySelectorAll('#map img.leaflet-tile-loaded').length")
            total = page.evaluate("() => document.querySelectorAll('#map img.leaflet-tile').length")
            return loaded, total

        tiles_loaded, tiles_total = tile_stats()
        # 主底图铺不满（无网络 / 被限制）时自动回退到备用底图
        if (tiles_total == 0 or tiles_loaded < tiles_total * 0.6) and basemap_count > 1:
            page.evaluate("() => window.__setBasemap__(1)")
            page.wait_for_timeout(2500)
            tiles_loaded, tiles_total = tile_stats()
            report.append("ℹ️ 主底图瓦片加载不足，已自动回退到备用底图: "
                          + str(page.evaluate("() => window.__basemapId__()")))
        if tiles_total == 0:
            report.append("⚠️ 底图瓦片未加载（无网络 / 底图源被限制），地图区域会空白；"
                          "左侧文字行程仍可正常交付")
        elif tiles_loaded < tiles_total * 0.8:
            report.append(f"⚠️ 底图瓦片加载不全: 已加载 {tiles_loaded}/{tiles_total}"
                          f"（地图可能‘稀碎’，请检查网络或换底图）")
        else:
            report.append(f"✅ 底图瓦片已加载: {tiles_loaded}/{tiles_total}")

        markers = page.evaluate("() => document.querySelectorAll('#map .leaflet-marker-icon').length")
        expected_markers = len([s for s in itin.get("stops", []) if s.get("lat") is not None and s.get("lng") is not None])
        if markers < expected_markers:
            report.append(f"⚠️ 地图标记缺失: 渲染={markers} 应有={expected_markers}"
                          f"（多为地理编码失败，请手填 lat/lng 后重跑）")
        else:
            report.append(f"✅ 地图标记齐全: {markers}")

        # 联动自检放到 PNG 截图之后（点击会打开气泡，若在截图前做会污染 PNG 画面）

        # 折叠自检（软检查）：点击某天标题，对应 day-body 应隐藏
        try:
            collapsed = page.evaluate(
                """() => {
                    var h = document.querySelector('#sidebar .day h2');
                    if (!h) return 'no-day';
                    h.click();
                    var hidden = getComputedStyle(h.closest('.day').querySelector('.day-body')).display === 'none';
                    h.click();  // 还原
                    return hidden ? 'ok' : 'fail';
                }"""
            )
            if collapsed == 'ok':
                report.append("✅ 『天』分组可折叠：点击标题可收起/展开")
            else:
                report.append("⚠️ 折叠功能未生效（不影响查看，可忽略）")
        except Exception:
            report.append("⚠️ 折叠自检跳过")

        if errors:
            ok = False
            report.append("❌ 页面 JS 错误: " + "; ".join(errors))
        else:
            report.append("✅ 无未捕获 JS 错误")

        # ---------- PNG 渲染 + 截断自检 ----------
        if want_png:
            sidebar_full = page.evaluate(
                "() => { var s = document.getElementById('sidebar'); return s.scrollHeight; }"
            )
            target = max(1000, sidebar_full + 44)

            # 极端高度安全上限：超过则无法在一张图内完整呈现，阻断并建议拆分
            if target > MAX_PNG_HEIGHT:
                ok = False
                report.append(
                    f"❌ 行程过长({sidebar_full}px)，单张 PNG 上限 {MAX_PNG_HEIGHT}px 仍会截断，"
                    f"建议拆分行程为两段或多张后再生成"
                )
            elif target > 2600:
                report.append(
                    f"⚠️ 行程较长，PNG 高度 {target}px（已完整渲染、无截断），建议拆分为多张便于查看/分享"
                )

            # 让整页随行程高度自适应：侧边栏展开、地图同步拉伸填充，保证文字永不裁切
            page.evaluate(
                """(h) => {
                    var s = document.getElementById('sidebar');
                    s.style.overflow = 'visible'; s.style.height = 'auto';
                    document.querySelector('.wrap').style.height = 'auto';
                    var el = document.getElementById('map'); el.style.height = h + 'px';
                    var m = window.__MAP__;
                    if (m) { m.invalidateSize(); if (window.__PTS__ && window.__PTS__.length) m.fitBounds(window.__PTS__, {padding:[40,40]}); }
                }""",
                target,
            )
            page.set_viewport_size({"width": 1600, "height": target})
            # 收起气泡并留足地图动画稳定时间，避免弹窗/半途动画被拍进 PNG
            page.evaluate("() => { if (window.__MAP__) window.__MAP__.closePopup(); }")
            page.wait_for_timeout(1200)
            # 布局变化后（拉高地图 + 重新 fitBounds）重跑一次标签避让，确保 PNG 里不压字
            page.evaluate("() => { if (window.__declutter__) window.__declutter__(); }")
            page.wait_for_timeout(120)
            page.screenshot(path=str(png_path), full_page=True)

            # 截断校验：侧边栏完整内容是否落在图片高度内（无内部滚动条 = 未裁切）
            fits = page.evaluate(
                "() => { var s = document.getElementById('sidebar'); return s.scrollHeight <= document.body.scrollHeight + 2; }"
            )
            if fits:
                report.append("✅ PNG 左侧行程完整无截断")
            else:
                ok = False
                report.append("❌ PNG 左侧行程疑似被截断（内容超出图片高度）")

            # 尺寸校验
            try:
                from PIL import Image
                with Image.open(png_path) as im:
                    w, h = im.size
                if (w, h) != (1600, target):
                    ok = False
                    report.append(f"❌ PNG 尺寸异常: {w}x{h} 期望 1600x{target}")
                else:
                    report.append(f"✅ PNG 尺寸正常: {w}x{h}")
            except Exception as e:  # noqa: BLE001
                report.append(f"⚠️ 无法读取 PNG 尺寸({e})，跳过尺寸校验")

            report.append(f"✅ PNG 已生成: {png_path}")

        # 标签避让检查：常驻景点名两两比对，重叠数应为 0（站点过密时可能仍有少量）
        try:
            lab = page.evaluate("""() => {
                var els = Array.prototype.slice.call(document.querySelectorAll('.leaflet-tooltip.mlabel'));
                var rs = els.map(function(e){ return e.getBoundingClientRect(); });
                var n = 0;
                for (var i=0;i<rs.length;i++) {
                  for (var j=i+1;j<rs.length;j++) {
                    var a=rs[i], b=rs[j];
                    if (!(a.right<b.left-1 || a.left>b.right+1 || a.bottom<b.top-1 || a.top>b.bottom+1)) n++;
                  }
                }
                return {n:n, total:els.length};
            }""")
            if lab["n"]:
                report.append(f"⚠️ 景点标签有 {lab['n']} 处重叠（站点过密，放大查看即可）")
            else:
                report.append(f"✅ 景点标签无重叠（{lab['total']} 个常驻标签）")
        except Exception:  # noqa: BLE001
            report.append("⚠️ 标签避让自检跳过")

        # 联动自检（软检查）：点击左侧第一个站点，地图应飞至对应标记并弹窗。
        # 放在截图之后执行，避免点击产生的气泡进入 PNG 画面。
        linkage = page.evaluate("() => (typeof focusStop === 'function') && (window.markersByIdx ? Object.keys(window.markersByIdx).length : 0) > 0")
        if linkage:
            page.evaluate("() => { var el = document.querySelector('#sidebar .stop'); if (el) el.click(); }")
            page.wait_for_timeout(1000)
            popup_open = page.evaluate("() => !!document.querySelector('.leaflet-popup')")
            if popup_open:
                report.append("✅ 左→右联动正常：点左侧站点地图已飞至对应标记并弹窗")
            else:
                report.append("⚠️ 左→右联动未触发弹窗（不影响查看，可忽略）")
        else:
            report.append("⚠️ 未检测到联动函数（focusStop/markersByIdx），点击左侧不会联动地图")

        browser.close()

    return ok, report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("itinerary", help="itinerary.json 路径")
    ap.add_argument("--out", default=None, help="输出目录（默认与 json 同目录）")
    ap.add_argument("--no-png", action="store_true", help="不生成 PNG")
    ap.add_argument("--skip-verify", action="store_true", help="跳过出图前自检（不推荐）")
    ap.add_argument("--geocode-only", action="store_true",
                    help="只解析坐标并打印核对表后退出（有缺失/低置信返回码 2），不出图")
    ap.add_argument("--dump-coords", action="store_true",
                    help="输出可粘贴进 references/poi-coords.json 的坐标片段")
    args = ap.parse_args()

    itin_path = Path(args.itinerary).resolve()
    itin = json.loads(itin_path.read_text(encoding="utf-8"))

    out = Path(args.out).resolve() if args.out else itin_path.parent
    out.mkdir(parents=True, exist_ok=True)

    ctx = itin.get("trip", {}).get("destination", "")
    stops = itin.get("stops", [])

    # 0) 手填坐标若标注为 GCJ-02（腾讯/高德/百度取来的），先换算成 WGS-84，避免二次偏移 300~600m
    for s in stops:
        if s.get("lat") is None or s.get("lng") is None:
            continue
        s["_src"] = "手填"
        if str(s.get("coord_source", "")).lower() in ("gcj02", "gcj-02", "gcj", "amap", "tencent", "qq"):
            s["lat"], s["lng"] = gcj_to_wgs(float(s["lat"]), float(s["lng"]))
            s["coord_source"] = "wgs84"
            s["_src"] = "手填（已由 GCJ-02 换算）"

    # 1) 缺坐标：本地缓存优先，再 Photon / Nominatim
    cache = load_coord_cache()
    for s in stops:
        if not s.get("name") or (s.get("lat") is not None and s.get("lng") is not None):
            continue
        name = s["name"]
        region = s.get("region") or ctx
        hit = cache_lookup(cache, name)
        if hit:
            lat, lng = float(hit["lat"]), float(hit["lng"])
            if str(hit.get("coord_source", "")).lower() in ("gcj02", "gcj-02", "gcj"):
                lat, lng = gcj_to_wgs(lat, lng)
                s["_src"] = "缓存（已由 GCJ-02 换算）"
            else:
                s["_src"] = "缓存"
            s["lat"], s["lng"] = lat, lng
            s["_meta"] = {"conf": "ok", "via": "cache", "admin": hit.get("note", ""), "osm": "cache"}
            continue
        lat, lng, meta = geocode(name, region)
        s["_meta"] = meta or {}
        if lat is not None:
            s["lat"], s["lng"] = lat, lng
            s["_src"] = "自动编码" if (meta or {}).get("conf") != "low" else "自动编码·低置信"
        if (meta or {}).get("via") == "nominatim":
            time.sleep(1.1)  # Nominatim 使用规范：请求间隔 ≥ 1s（Photon 不需要）

    # 2) 出图前坐标核对表：坐标 + 来源 + 命中的行政层级 + 与上一站距离，便于发现错位/误命中
    print("\n--- 站点坐标核对表（出图前请确认与预期一致）---")
    geo_failed, low_conf = False, False
    prev = None
    for s in stops:
        if not s.get("name"):
            continue
        if s.get("lat") is None or s.get("lng") is None:
            meta = s.get("_meta") or {}
            hint = "、".join(meta.get("tried") or []) or "无"
            print(f"  ⚠️  {s['name']}: 坐标缺失（已试查询词：{hint}）→ 请手填 lat/lng 后重跑，"
                  f"或补进 references/poi-coords.json")
            geo_failed = True
            continue
        meta = s.get("_meta") or {}
        lat, lng = float(s["lat"]), float(s["lng"])
        extra = []
        if meta.get("admin"):
            extra.append(meta["admin"])
        if meta.get("osm") and meta.get("via") != "cache":
            extra.append(meta["osm"])
        if prev:
            extra.append(f"距上一站 {straight_km(prev[0], prev[1], lat, lng):.0f}km")
        flag = ""
        if meta.get("conf") == "low":
            flag = "  ⚠️ 低置信：仅命中省级归属或名称部分匹配，请人工确认"
            low_conf = True
        elif meta.get("alt"):
            flag = f"  （次选 {meta['alt'][0]}）"
        print(f"  •  {s['name']}: ({lat}, {lng}) [{s.get('_src', '手填')}] "
              + (" · ".join(extra) if extra else "") + flag)
        prev = (lat, lng)
    if geo_failed:
        print("  ⚠️ 存在坐标缺失站点，地图标记将不完整，建议修正后重跑。")
    if low_conf:
        print("  ⚠️ 存在低置信坐标，务必核对后再交付（对照 references/coordinate-sources.md）。")

    if args.dump_coords:
        dump = {}
        for s in stops:
            if s.get("name") and s.get("lat") is not None:
                dump[s["name"]] = {"lat": round(float(s["lat"]), 5), "lng": round(float(s["lng"]), 5),
                                   "coord_source": "wgs84", "note": s.get("region", "")}
        print("\n--- 可粘贴进 references/poi-coords.json 的片段 ---")
        print(json.dumps(dump, ensure_ascii=False, indent=2))

    if args.geocode_only:
        print("\nℹ️ --geocode-only：仅核对坐标，未生成 HTML/PNG。")
        return 2 if (geo_failed or low_conf) else 0

    # 中国大陆站点额外算一份 GCJ-02 坐标（高德底图用），原始 WGS-84 保留供 OSM/CARTO 使用
    for s in itin.get("stops", []):
        if s.get("lat") is None or s.get("lng") is None:
            continue
        glng, glat = wgs84_to_gcj02(float(s["lng"]), float(s["lat"]))
        if (glng, glat) != (float(s["lng"]), float(s["lat"])):
            s["lng_gcj"], s["lat_gcj"] = glng, glat
        for k in ("_src", "_meta"):  # 内部字段不进入页面数据
            s.pop(k, None)

    basemap_ids = plan_basemaps(itin)
    print(f"\n--- 底图 ---\n  主底图: {basemap_ids[0]}（可在地图页「风格」切换: {', '.join(basemap_ids)}；"
          + "  页面内亦支持 watercolor/vintage/sticker/original 风格切换，[可用 trip.basemap: amap|osm|carto|esri_physical 覆盖]）")

    html = build_html(itin, basemap_ids)
    html_path = out / "travel_map.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"✅ HTML: {html_path}")

    if args.no_png:
        png_path = None
    else:
        png_path = out / "route_map.png"

    print("\n--- 出图前自检 ---")
    if args.skip_verify:
        # 跳过自检但仍尽量出 PNG
        if png_path is not None:
            _, _ = verify_and_render(html_path, png_path, itin, want_png=True, basemap_count=len(basemap_ids))
            print("⚠️ 已跳过自检（--skip-verify），直接生成 PNG")
        else:
            print("⚠️ 已跳过自检（--skip-verify）")
        return

    ok, report = verify_and_render(html_path, png_path, itin,
                                   want_png=(png_path is not None),
                                   basemap_count=len(basemap_ids))
    for line in report:
        print("  " + line)
    warn_count = sum(1 for line in report if line.startswith("⚠️"))

    if not ok:
        print("\n❌ 自检未通过：请勿交付，请先排查上方 ❌ 项（常见问题：占位符未替换、"
              "行程未渲染、JS 报错、PNG 被截断）。")
        sys.exit(1)
    if warn_count:
        print(f"\n✅ 可交付（{warn_count} 项 ⚠️ 为环境类提示，如底图空白/缺 playwright，"
              f"不影响 HTML 行程内容，按需处理即可）。")
    else:
        print("\n✅ 自检全部通过，可交付。")


if __name__ == "__main__":
    sys.exit(main())
