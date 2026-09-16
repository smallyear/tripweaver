#!/usr/bin/env python3
"""读取 itinerary.json，生成可缩放地图 HTML 与带文字行程的路线图片 PNG，并做「出图前自检」。

用法:
    python3 generate_travel.py <itinerary.json> [--out <目录>] [--no-png] [--skip-verify]

- 站点缺 lat/lng 时，自动用 Nominatim(OSM) 按地名地理编码（WGS-84）。
- HTML 用 Leaflet + OpenStreetMap（浏览器直接打开即可缩放/拖动）。
- PNG 用 Playwright 截图（需 pip install playwright && playwright install chromium）。
- 自检：HTML 无占位符残留/无 JS 错误/行程与标记齐全/地图瓦片加载；PNG 无截断且尺寸正常。
  任一关键项失败会以退出码 1 中止，提醒「不要交付，先排查」。
"""
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from math import sin, cos, pi
from pathlib import Path

DAY_COLORS = [
    "#e63946", "#f4a261", "#2a9d8f", "#4361ee", "#7209b7",
    "#f72585", "#fb8500", "#06d6a0", "#118ab2", "#8338ec",
]

UA = "travel-planner/1.0 (WorkBuddy)"
MAX_PNG_HEIGHT = 6000  # PNG 高度安全上限，超过则阻断并建议拆分行程


def geocode(name, ctx):
    """用 Nominatim 把地名解析为 WGS-84 的 (lat, lng)。失败时返回 (None, None)。
    ctx 优先用 stop 自带的 region（市/县），其次 trip.destination。"""
    q = f"{name}, {ctx}" if ctx else name
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"format": "json", "q": q, "limit": 1, "accept-language": "zh-CN"}
    )
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.load(r)
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] 地理编码失败: {name} ({e})", file=sys.stderr)
    return None, None


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
</style>
</head>
<body>
<div class="wrap">
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
  });
  sec.appendChild(body);
  // 折叠/展开：点击当天标题切换，箭头同步
  h2.addEventListener('click', function(){ sec.classList.toggle('collapsed'); });
  sb.appendChild(sec);
});

// ---- 地图（Leaflet + 高德底图，国内可达、中文路网标注全） ----
var map = L.map('map', { zoomControl: true });
L.tileLayer('https://wprd0{s}.is.autonavi.com/appmaptile?x={x}&y={y}&z={z}&lang=zh_cn&size=1&scl=1&style=7', { subdomains: '1234', maxZoom: 19, attribution: '© 高德地图' }).addTo(map);
var pts = [];
var prev = null;
stops.forEach(function(s){
  if (s.lat == null || s.lng == null) return;
  var ll = [s.lat, s.lng]; pts.push(ll);
  var color = DAYCOLORS[s.day] || '#4361ee';
  var icon = L.divIcon({ className: '', html:
    '<div style="background:'+color+';width:26px;height:26px;border-radius:50% 50% 50% 0;transform:rotate(-45deg);border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.4);display:flex;align-items:center;justify-content:center;"><span style="transform:rotate(45deg);color:#fff;font-size:12px;font-weight:700;">'+s.day+'</span></div>',
    iconSize: [26,26], iconAnchor: [13,26] });
  var popup = '<div class="pop-title">第'+s.day+'天 '+(s.time||'')+' · '+esc(s.name)+'</div>'+(s.note?'<div class="pop-note">'+esc(s.note)+'</div>':'');
  var mk = L.marker(ll, { icon: icon }).addTo(map).bindPopup(popup);
  markersByIdx[s.__i] = mk;
  mk.on('click', function(){ highlightSidebar(s.__i); });  // 地图→左侧反联动
  // 常驻名称标签：每个数字标记旁直接显示景点名（无需点击）
  mk.bindTooltip(esc(s.name), { permanent: true, direction: 'right', offset: [10, 0], className: 'mlabel' });
  // 连续实线：按序连接所有站点（跨天也连），形成完整路线而非分段断线
  if (prev) L.polyline([prev, ll], { color: color, weight: 4, opacity: .85 }).addTo(map);
  prev = ll;
});
// 环线闭合：若首末站点同名（出发地=返程地），用虚线把终点连回起点
if (pts.length > 2) {
  var fIdx = stops.findIndex(function(s){ return s.lat != null && s.lng != null; });
  var lIdx = -1;
  for (var i = stops.length - 1; i >= 0; i--) { if (stops[i].lat != null && stops[i].lng != null) { lIdx = i; break; } }
  if (fIdx >= 0 && lIdx >= 0 && stops[fIdx].name === stops[lIdx].name) {
    L.polyline([pts[pts.length - 1], pts[0]], { color: DAYCOLORS[stops[fIdx].day] || '#4361ee', weight: 4, opacity: .85, dashArray: '2,8' }).addTo(map);
  }
}
if (pts.length) map.fitBounds(pts, { padding: [40,40] }); else map.setView([35,105], 4);
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
    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * pi
    magic = sin(radlat)
    magic = 1 - _GCJ_EE * magic * magic
    sqrtmagic = magic ** 0.5
    dlat = (dlat * 180.0) / ((_GCJ_A * (1 - _GCJ_EE)) / (magic * sqrtmagic) * pi)
    dlng = (dlng * 180.0) / (_GCJ_A / sqrtmagic * cos(radlat) * pi)
    return lng + dlng, lat + dlat


def build_html(itin):
    data_json = json.dumps(itin, ensure_ascii=False).replace("</", "<\\/")
    days = sorted({int(s["day"]) for s in itin.get("stops", []) if s.get("day") is not None})
    day_color = {d: DAY_COLORS[i % len(DAY_COLORS)] for i, d in enumerate(days)}
    title = (itin.get("trip", {}).get("title") or "旅行行程")
    return (HTML_TEMPLATE
            .replace("__DATA__", data_json)
            .replace("__DAYCOLORS__", json.dumps(day_color, ensure_ascii=False))
            .replace("__TITLE__", title))


def verify_and_render(html_path, png_path, itin, want_png):
    """启动一次 Playwright 会话：渲染 PNG（自适应高度防截断）+ 跑全套自检，返回 (ok, report_lines)。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False, ["⚠️ 未安装 playwright，跳过自检与 PNG。安装: pip install playwright && playwright install chromium"]

    report = []
    ok = True
    errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
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

        tiles_loaded = page.evaluate("() => document.querySelectorAll('#map img.leaflet-tile-loaded').length")
        tiles_total = page.evaluate("() => document.querySelectorAll('#map img.leaflet-tile').length")
        if tiles_total == 0:
            ok = False
            report.append("❌ 地图瓦片未加载（可能无网络 / OSM 被限制），底图会空白")
        elif tiles_loaded < tiles_total * 0.8:
            ok = False
            report.append(f"❌ 地图瓦片加载不全: 已加载 {tiles_loaded}/{tiles_total}（底图会‘稀碎’，检查网络或换底图）")
        else:
            report.append(f"✅ 地图瓦片已加载: {tiles_loaded}/{tiles_total}")

        markers = page.evaluate("() => document.querySelectorAll('#map .leaflet-marker-icon').length")
        expected_markers = len([s for s in itin.get("stops", []) if s.get("lat") is not None and s.get("lng") is not None])
        if markers < expected_markers:
            ok = False
            report.append(f"❌ 地图标记缺失: 渲染={markers} 应有={expected_markers}（检查 lat/lng 或地理编码是否成功）")
        else:
            report.append(f"✅ 地图标记齐全: {markers}")

        # 联动自检（软检查，不影响交付）：点击左侧第一个站点，地图应飞至对应标记并弹窗
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
            page.wait_for_timeout(800)
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

        browser.close()

    return ok, report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("itinerary", help="itinerary.json 路径")
    ap.add_argument("--out", default=None, help="输出目录（默认与 json 同目录）")
    ap.add_argument("--no-png", action="store_true", help="不生成 PNG")
    ap.add_argument("--skip-verify", action="store_true", help="跳过出图前自检（不推荐）")
    args = ap.parse_args()

    itin_path = Path(args.itinerary).resolve()
    itin = json.loads(itin_path.read_text(encoding="utf-8"))

    out = Path(args.out).resolve() if args.out else itin_path.parent
    out.mkdir(parents=True, exist_ok=True)

    ctx = itin.get("trip", {}).get("destination", "")
    missing = [s for s in itin.get("stops", []) if (s.get("lat") is None or s.get("lng") is None) and s.get("name")]
    for s in missing:
        # 优先用 stop 自带 region（市/县）作地理编码上下文，多城环线下比 destination 更准
        region = s.get("region") or ctx
        lat, lng = geocode(s["name"], region)
        if lat is not None:
            s["lat"], s["lng"] = lat, lng
        time.sleep(1.1)  # Nominatim 使用规范：请求间隔 ≥ 1s

    # 出图前坐标核对表：列出每个站点的解析坐标，便于发现明显错位（如标到邻市）
    print("\n--- 站点坐标核对表（出图前请确认与预期一致）---")
    geocoded_names = {s.get("name") for s in missing}
    geo_failed = False
    for s in itin.get("stops", []):
        if not s.get("name"):
            continue
        if s.get("lat") is None or s.get("lng") is None:
            print(f"  ⚠️  {s['name']}: 坐标缺失（地理编码失败，请手动补 lat/lng 或核对地名）")
            geo_failed = True
            continue
        tag = "自动编码" if s["name"] in geocoded_names else "手填"
        print(f"  •  {s['name']}: ({s['lat']}, {s['lng']}) [{tag}]")
    if geo_failed:
        print("  ⚠️ 存在坐标缺失站点，地图标记将不完整，建议修正后重跑。")

    # 坐标转换：存入 JSON 的是真实 WGS-84，渲染前转 GCJ-02 以贴合高德底图
    for s in itin.get("stops", []):
        if s.get("lat") is not None and s.get("lng") is not None:
            glng, glat = wgs84_to_gcj02(float(s["lng"]), float(s["lat"]))
            s["lng"], s["lat"] = glng, glat

    html = build_html(itin)
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
            ok, _ = verify_and_render(html_path, png_path, itin, want_png=True)
            print("⚠️ 已跳过自检（--skip-verify），直接生成 PNG")
        else:
            print("⚠️ 已跳过自检（--skip-verify）")
        return

    ok, report = verify_and_render(html_path, png_path, itin, want_png=(png_path is not None))
    for line in report:
        print("  " + line)

    if not ok:
        print("\n❌ 自检未通过：请勿交付，请先排查上方 ❌ 项（常见问题：无网络导致瓦片空白、"
              "经纬度缺失导致标记丢失、行程过长导致截断）。")
        sys.exit(1)
    print("\n✅ 自检全部通过，可交付。")


if __name__ == "__main__":
    main()
