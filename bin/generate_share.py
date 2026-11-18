#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""无地图分享图生成器（Agent 模式新增）。

读取 itinerary.json + illustrations/ 目录，生成四类「不带底图」的分享图 PNG：
  1) 每日海报   share/day_XX.png        —— 当日插画 + 手写标题 + 日期 + 当日关键词
  2) 封面 hero  share/cover_hero.png    —— 横版纯插画 + 行程标题/日期区间
  3) 景点九宫格 share/grid.png          —— 全部可用插画拼成一张速览图
  4) 金句卡片   share/quote_XX.png      —— 插画 + 手写句子，氛围收尾图

设计原则（与 travel_map 的手账风一致，但完全不依赖地图底图）：
  - 手写体走 macOS 系统字体栈（HanziPen/Hannotate/楷体），不依赖外部 CDN。
  - 插画缺失时优雅降级为「纸卡 + 站名」，不报错、不阻断。
  - 文字一律页面排版叠加，不靠 AI 写中文（AI 写中文字不可靠）。
  - 渲染复用系统已装 Chrome（与 generate_travel.py 同链路），无需下载 chromium。

用法：
  python bin/generate_share.py <itinerary.json> [--out <dir>] [--types all|day|cover|grid|quote]
"""
import argparse
import datetime as dt
import html
import json
import math
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path

# 手写体字体栈（macOS 系统可用，无需联网）
FONT_STACK = ('"HanziPen SC","Hannotate SC","STKaiti","楷体-简",'
              '"Kaiti SC","KaiTi","Songti SC",cursive')

# 每日海报柔和水彩配色（与地图 watercolor 主题呼应，但更柔）
DAY_COLORS = ["#e8a87c", "#c38d9e", "#85b9b0", "#f2c14e",
              "#9bb8a6", "#d98e9e", "#7fa6c9", "#e0a96d",
              "#a3c4a8", "#cf9bb0"]

# 金句池（自然 / 亲子 / 慢游调性，无特定景点指向，通用）
QUOTES = [
    "慢慢走，才能看见风的形状。",
    "最好的课堂，是大山与河流。",
    "把日子过成一场不必赶路的旅行。",
    "去有风的地方，把心放轻。",
]

# 设备像素比：2 出高清图，社交平台缩放显示更锐利
SCALE = 2


def esc(t):
    return html.escape("" if t is None else str(t), quote=True)


def load_itin(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def start_date(itin):
    s = (itin.get("trip") or {}).get("start_date")
    if not s:
        return None
    try:
        return dt.date.fromisoformat(s)
    except ValueError:
        return None


def day_date(sd, day):
    if not sd:
        return ""
    return (sd + dt.timedelta(days=day - 1)).strftime("%Y.%m.%d")


# 由 main() 设置为本次 share 输出目录：插画用「相对 HTML 的路径」引用，
# 因此 --out 指到行程目录之外也能正常加载（曾因写死 ../illustrations/ 导致 404）。
_HTML_DIR = None


def _img_ref(p):
    """把插画绝对路径转成 HTML 可用的相对引用（保留中文，做百分号编码）。"""
    if _HTML_DIR:
        rel = os.path.relpath(p, _HTML_DIR).replace(os.sep, "/")
        return urllib.parse.quote(rel, safe="/.:")
    return "../illustrations/" + urllib.parse.quote(p.name, safe="")


def illu_path(illu_dir, name):
    """返回插画引用路径；不存在返回 None。

    磁盘文件用中文真名（<站名>.png）；file:// 加载时会解码百分号编码，
    正好匹配磁盘中文文件名。（历史坑：磁盘文件别命名成 %E9… 编码）
    """
    if not illu_dir:
        return None
    p = illu_dir / (name + ".png")
    return _img_ref(p) if p.exists() else None


def cover_path(illu_dir):
    if illu_dir and (illu_dir / "cover.png").exists():
        return _img_ref(illu_dir / "cover.png")
    return None


# ---------------------------------------------------------------------------
# 地图快照：复用 generate_travel.py 的 Leaflet 页面截图（不依赖 ImageGen 积分）
# ---------------------------------------------------------------------------
def _load_map_module():
    """按文件路径加载 generate_travel.py（同目录脚本，避免包名冲突）。"""
    import importlib.util
    path = Path(__file__).resolve().parent / "generate_travel.py"
    spec = importlib.util.spec_from_file_location("tripweaver_travel", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _prepare_map_itin(mod, itin):
    """地图快照前补齐坐标，并给国内站点补一份 GCJ-02（高德底图用）。

    坐标来源与 generate_travel 主流程一致：本地缓存 → Photon → Nominatim。
    这样即使 itinerary.json 只写了站名，地图海报也能独立生成。
    """
    ctx = itin.get("trip", {}).get("destination", "")
    cache = mod.load_coord_cache()
    for s in itin.get("stops", []):
        if not s.get("name"):
            continue
        if s.get("lat") is None or s.get("lng") is None:
            hit = mod.cache_lookup(cache, s["name"])
            if hit:
                s["lat"], s["lng"] = float(hit["lat"]), float(hit["lng"])
            else:
                lat, lng, meta = mod.geocode(s["name"], s.get("region") or ctx)
                if lat is not None:
                    s["lat"], s["lng"] = lat, lng
                    if (meta or {}).get("via") == "nominatim":
                        time.sleep(1.1)
        if s.get("lat") is None or s.get("lng") is None:
            continue
        glng, glat = mod.wgs84_to_gcj02(float(s["lng"]), float(s["lat"]))
        if (glng, glat) != (float(s["lng"]), float(s["lat"])):
            s["lng_gcj"], s["lat_gcj"] = glng, glat


def key_map_labels(stops, max_n=5):
    """整趟海报用：每天挑一个有代表性的景点名，总量封顶（避免 1080 宽下标签糊成一团）。"""
    skip = ("机场", "县城", "服务区", "车站", "酒店")
    picked, seen = [], set()
    for s in stops:
        name = s.get("name") or ""
        if not name or name.endswith("市") or any(k in name for k in skip):
            continue
        if s.get("day") in seen:
            continue
        seen.add(s.get("day"))
        picked.append(name)
    if len(picked) > max_n:
        step = len(picked) / max_n
        picked = [picked[int(i * step)] for i in range(max_n)]
    return picked


def render_map_shots(itin, shots, out_dir):
    """按 shots 渲染多张地图快照。shots: [{name, w, h, days, key_names}]

    返回 (refs|{name: 相对路径}, engine|None, error|str)
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {}, None, "未安装 playwright，无法生成地图快照"
    try:
        mod = _load_map_module()
    except Exception as e:  # noqa: BLE001
        return {}, None, f"无法复用地图渲染模块：{e}"

    _prepare_map_itin(mod, itin)
    if not any(s.get("lat") is not None and s.get("lng") is not None for s in itin.get("stops", [])):
        return {}, None, "行程没有可用坐标（先运行 generate_travel.py 完成地理编码）"
    html = mod.build_html(itin, mod.plan_basemaps(itin))
    tmp = out_dir / "_map_source.html"
    tmp.write_text(html, encoding="utf-8")

    refs = {}
    try:
        with sync_playwright() as p:
            browser, label = launch_browser(p)
            page = browser.new_page(viewport={"width": 1600, "height": 1000},
                                    device_scale_factor=SCALE)
            page.goto("file://" + str(tmp))
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(1200)
            for shot in shots:
                page.set_viewport_size({"width": shot["w"], "height": shot["h"]})
                page.evaluate(
                    """(a) => {
                        var sb = document.querySelector('.sidebar'); if (sb) sb.style.display = 'none';
                        document.querySelectorAll('.leaflet-control-zoom').forEach(function(e){ e.style.display = 'none'; });
                        var w = document.querySelector('.wrap');
                        w.style.display = 'block'; w.style.height = a.h + 'px';
                        var el = document.getElementById('map');
                        el.style.width = a.w + 'px'; el.style.height = a.h + 'px';
                        var m = window.__MAP__;
                        m.invalidateSize();
                        document.querySelectorAll('.leaflet-tooltip.mlabel').forEach(function(x){ x.style.display = ''; });
                        if (window.__filterDay__) window.__filterDay__(a.days || null);
                        var pts = a.days
                            ? stops.filter(function(s){ return a.days.indexOf(s.day) >= 0 && s.lat != null; }).map(coordOf)
                            : window.__PTS__;
                        if (!pts || !pts.length) pts = window.__PTS__;
                        if (!pts || !pts.length) return 'no-points';
                        if (pts.length === 1) {
                            m.setView(pts[0], a.singleZoom || 12);
                        } else {
                            m.fitBounds(pts, {padding: [Math.round(a.w * 0.04), Math.round(a.h * 0.05)]});
                        }
                        return 'ok';
                    }""",
                    {"w": shot["w"], "h": shot["h"], "days": shot.get("days")},
                )
                page.wait_for_timeout(1100)
                tiles = page.evaluate("() => document.querySelectorAll('#map img.leaflet-tile-loaded').length")
                if not tiles:
                    raise RuntimeError("底图瓦片未加载（无网络或底图源不可达）")
                if shot.get("key_names"):
                    page.evaluate(
                        """(keep) => {
                            document.querySelectorAll('.leaflet-tooltip.mlabel').forEach(function(el){
                                if (keep.indexOf(el.textContent) < 0) el.style.display = 'none';
                            });
                        }""",
                        shot["key_names"],
                    )
                page.evaluate("() => { if (window.__declutter__) window.__declutter__(); }")
                page.wait_for_timeout(200)
                png = out_dir / ("_map_" + shot["name"] + ".png")
                page.locator("#map").screenshot(path=str(png))
                refs[shot["name"]] = _img_ref(png)
            browser.close()
        return refs, label, ""
    except Exception as e:  # noqa: BLE001
        return {}, None, f"地图快照渲染失败：{e}"


# ---------------------------------------------------------------------------
# 共用样式片段
# ---------------------------------------------------------------------------
PAPER_CSS = """
  * { box-sizing: border-box; margin:0; padding:0; }
  html,body { width:100%; height:100%; }
  body {
    font-family: __FONT__;
    background:
      radial-gradient(circle at 20% 15%, rgba(255,255,255,.6), transparent 40%),
      radial-gradient(circle at 85% 80%, rgba(255,247,230,.7), transparent 45%),
      #f7efe0;
    color:#4a4036;
  }
  .frame {
    position:relative; width:100%; height:100%;
    border:3px solid #d8c4a0; border-radius:14px;
    box-shadow: inset 0 0 0 8px #fbf5e9, 0 6px 22px rgba(120,90,50,.18);
    overflow:hidden;
  }
  .tape {
    position:absolute; width:120px; height:34px;
    background:rgba(220,200,160,.55);
    box-shadow:0 1px 3px rgba(0,0,0,.08);
    transform:rotate(-6deg);
  }
  .hand { font-family: __FONT__; }
  .illu {
    object-fit:cover; border-radius:12px;
    box-shadow:0 6px 18px rgba(120,90,50,.22);
    background:#efe6d4;
  }
  .ph {
    display:flex; align-items:center; justify-content:center;
    border:2px dashed #c9b48c; border-radius:12px;
    color:#a08b66; font-size:22px; text-align:center; padding:12px;
    background:#f1e8d6;
  }
"""


def render_img(src, cls="illu", w=None, h=None, onerror_hide=False):
    """生成 <img>，缺失（src=None）时降级为纸卡占位。"""
    if not src:
        style = ""
        if w:
            style += f"width:{w}px;"
        if h:
            style += f"height:{h}px;"
        return f'<div class="ph {cls}" style="{style}">插画待生成</div>'
    oe = "this.style.display='none';this.nextElementSibling.style.display='flex';" if onerror_hide else ""
    return (f'<img class="{cls}" src="{esc(src)}" onerror="{oe}" '
            f'style="{"width:"+str(w)+"px;" if w else ""}{"height:"+str(h)+"px;" if h else ""}"/>')


def page_wrap(inner_css, body):
    return f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<style>{PAPER_CSS.replace("__FONT__", FONT_STACK)}{inner_css}</style></head>
<body><div class="frame">{body}</div></body></html>"""


# ---------------------------------------------------------------------------
# 形态 1：每日海报（竖版 1080x1440）
# ---------------------------------------------------------------------------
def build_daily_poster(day, day_stops, sd, illu_dir, trip=None):
    accent = DAY_COLORS[(day - 1) % len(DAY_COLORS)]
    # 头条：优先有插画的站；否则非机场站；否则第一站
    headline = None
    for s in day_stops:
        if illu_path(illu_dir, s["name"]):
            headline = s
            break
    if not headline:
        for s in day_stops:
            if "机场" not in s["name"]:
                headline = s
                break
    if not headline:
        headline = day_stops[0]

    hname = headline["name"]
    hregion = headline.get("region", "")
    himg = illu_path(illu_dir, hname)
    if not himg:
        himg = cover_path(illu_dir)  # 退回封面，避免空白

    # 页脚取自行程主题首个标签；缺失时只写「旅途手账」，不硬编码亲子
    theme = ((trip or {}).get("theme") or "").strip()
    tag = theme.replace("／", "/").split("/")[0].strip()[:8] if theme else ""
    foot = "旅途手账" + (" · " + tag if tag else "")

    # 当日站点最多展示 4 条，避免长行程撑出画面；超长站名省略号截断
    shown = day_stops[:4]
    keywords = "".join(
        f'<div class="kw"><span class="dot"></span><span class="kwname">{esc(s["name"])}'
        f'{(" · " + esc(s["time"])) if s.get("time") else ""}</span></div>'
        for s in shown
    )
    if len(day_stops) > len(shown):
        keywords += f'<div class="kw more">…… 另有 {len(day_stops) - len(shown)} 站</div>'

    # 长站名自动缩字号（如「中科院西双版纳热带植物园」），避免顶出画面
    tsize = 64 if len(hname) <= 12 else (52 if len(hname) <= 16 else 42)

    # 无插画时不做大空框，改成「文​字优先」的纯排版海报
    if himg:
        hero = f'<div class="hero">{render_img(himg, w=720, h=600)}</div>'
        poster_cls = "poster"
    else:
        dest = ((trip or {}).get("destination") or "").split()[0] if (trip or {}).get("destination") else "旅途手账"
        hero = (f'<div class="stamp"><div class="stamp-dest">{esc(dest)}</div>'
                f'<div class="stamp-line"></div><div class="stamp-sub">DAY {day} · 旅途手账</div></div>')
        poster_cls = "poster noimg"

    css = """
    .poster{position:relative;width:100%;height:100%;padding:64px 60px;}
    .badge{display:inline-block;background:__ACC__;color:#fff;border-radius:30px;
      padding:10px 26px;font-size:30px;letter-spacing:2px;box-shadow:0 3px 8px rgba(0,0,0,.12);}
    .date{margin-top:18px;font-size:30px;color:#8a7558;}
    .hero{margin:34px auto 10px;width:720px;height:600px;transform:rotate(-1.2deg);
      display:flex;align-items:center;justify-content:center;}
    .hero img,.hero .ph{width:720px;height:600px;}
    .tape.t1{top:40px;left:80px;} .tape.t2{top:40px;right:80px;transform:rotate(7deg);}
    .title{text-align:center;font-size:__TITLE_SIZE__px;color:#4a4036;margin-top:18px;
      line-height:1.2;padding:0 24px;word-break:break-word;}
    .sub{text-align:center;font-size:30px;color:#9a8360;margin-top:10px;}
    .divider{width:360px;height:3px;background:__ACC__;opacity:.5;margin:26px auto;border-radius:3px;}
    .kws{margin:6px auto 0;width:680px;}
    .kw{font-size:32px;color:#5a4f40;margin:12px 0;display:flex;align-items:center;}
    .kwname{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
    .kw.more{font-size:26px;color:#a08b66;}
    .dot{width:14px;height:14px;border-radius:50%;background:__ACC__;margin-right:18px;flex:0 0 auto;}
    .foot{position:absolute;bottom:46px;left:0;right:0;text-align:center;font-size:24px;color:#b3a081;}
    /* 无插画：文字优先的邮戳式排版 */
    .poster.noimg .stamp{width:760px;margin:130px auto 40px;padding:56px 40px;
      border:3px dashed #cbb894;border-radius:18px;transform:rotate(-1.5deg);text-align:center;}
    .poster.noimg .stamp-dest{font-size:76px;color:#4a4036;line-height:1.2;}
    .poster.noimg .stamp-line{width:220px;height:3px;background:__ACC__;opacity:.55;margin:32px auto;}
    .poster.noimg .stamp-sub{font-size:30px;color:#8a7558;letter-spacing:2px;}
    .poster.noimg .title{margin-top:34px;}
    """
    css = css.replace("__ACC__", accent).replace("__TITLE_SIZE__", str(tsize))
    body = f"""
      <div class="tape t1"></div><div class="tape t2"></div>
      <div class="{poster_cls} hand">
        <div class="badge">DAY {day}</div>
        <div class="date">{esc(day_date(sd, day))}</div>
        {hero}
        <div class="title">{esc(hname)}</div>
        <div class="sub">{esc(hregion)}</div>
        <div class="divider"></div>
        <div class="kws">{keywords}</div>
        <div class="foot">{esc(foot)}</div>
      </div>"""
    return page_wrap(css, body), (1080, 1440)


# ---------------------------------------------------------------------------
# 形态 2：封面 hero（横版 1600x1000）
# ---------------------------------------------------------------------------
def build_cover(itin, illu_dir):
    trip = itin.get("trip") or {}
    title = trip.get("title", "旅行手账")
    dest = trip.get("destination", "")
    sd = start_date(itin)
    days = trip.get("days")
    drange = ""
    if sd and days:
        end = sd + dt.timedelta(days=days - 1)
        drange = f"{sd.strftime('%Y.%m.%d')} – {end.strftime('%Y.%m.%d')} · 共 {days} 天"
    elif sd:
        drange = sd.strftime("%Y.%m.%d")
    travelers = trip.get("travelers", "")
    cov = cover_path(illu_dir)

    css = """
    .hero{position:relative;width:100%;height:100%;}
    .bg{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;}
    .bgph{position:absolute;inset:0;background:linear-gradient(135deg,#e8d9bd,#cdb891);}
    .veil{position:absolute;inset:0;
      background:linear-gradient(180deg,rgba(247,239,224,.30) 0%,rgba(247,239,224,.78) 58%,rgba(247,239,224,.94) 100%);}
    .center{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:0 120px;}
    .kicker{font-size:30px;color:#8a7558;letter-spacing:6px;margin-bottom:14px;}
    .title{font-size:84px;color:#3f362b;line-height:1.18;text-shadow:0 2px 10px rgba(255,255,255,.5);}
    .rule{width:300px;height:4px;background:#c98a4b;border-radius:4px;margin:34px 0;}
    .meta{font-size:34px;color:#5a4f40;}
    .sub{font-size:28px;color:#8a7558;margin-top:14px;}
    """
    bg = render_img(cov, w=1600, h=1000) if cov else '<div class="bgph"></div>'
    body = f"""
      {bg}
      <div class="veil"></div>
      <div class="center hand">
        <div class="kicker">旅 途 手 账</div>
        <div class="title">{esc(title)}</div>
        <div class="rule"></div>
        <div class="meta">{esc(drange)}</div>
        <div class="sub">{esc(dest)}{(' · ' + esc(travelers)) if travelers else ''}</div>
      </div>"""
    return page_wrap(css, body), (1600, 1000)


# ---------------------------------------------------------------------------
# 形态 3：景点九宫格（方版 1200x1200）
# ---------------------------------------------------------------------------
def build_grid(itin, stops, illu_dir):
    trip = itin.get("trip") or {}
    title = trip.get("title", "目的地速览")
    items = []
    seen = set()
    for s in stops:
        name = s["name"]
        if name in seen:  # 同一站跨天重复出现（如告庄西双景）只入一格
            continue
        seen.add(name)
        p = illu_path(illu_dir, name)
        if p:
            items.append((p, name))
    n = len(items)
    # 列数：3 张铺满一行，4 张排 2×2；5 张以上回 3 列
    cols = 1 if n <= 1 else (2 if n in (2, 4) else 3)
    rows = max(1, (n + cols - 1) // cols)
    # 1200 方版里 cells 可用高度约 880px；按行数反推单格边长，
    # 否则插画变多变 3 行时图注会被挤出画布（曾溢出 240px）。
    gap, cap_h = 30, 78
    cell = min(320, max(150, int((880 - gap * (rows - 1)) / rows) - 14 - cap_h))
    cap_fs = 26 if cell >= 280 else 22
    # 标题过长时拆出尾部的「（日期）」，避免在括号中间断行
    main_title, tail_title = title, ""
    for l, r in (("（", "）"), ("(", ")")):
        if title.endswith(r) and l in title:
            idx = title.rfind(l)
            main_title, tail_title = title[:idx], title[idx:]
            break
    tsize = 56 if len(main_title) <= 12 else (48 if len(main_title) <= 17 else 40)
    cells = ""
    for p, name in items:
        cells += f"""
          <div class="cell">
            {render_img(p, w=cell, h=cell)}
            <div class="cap hand">{esc(name)}</div>
          </div>"""
    if not cells:
        cells = '<div class="cap hand" style="font-size:40px;color:#a08b66;">（暂无插画，先给站点生成插画）</div>'

    css = """
    .grid{position:relative;width:100%;height:100%;padding:70px 60px;display:flex;flex-direction:column;}
    .head{text-align:center;font-size:__TSIZE__px;color:#3f362b;margin-bottom:8px;line-height:1.25;}
    .headsub{text-align:center;font-size:30px;color:#8a7558;margin-bottom:10px;}
    .sub{text-align:center;font-size:28px;color:#8a7558;margin-bottom:34px;}
    .cells{display:grid;grid-template-columns:repeat(__COLS__,1fr);gap:30px;justify-items:center;align-content:center;flex:1;}
    .cell{display:flex;flex-direction:column;align-items:center;}
    .cell img,.cell .ph{width:__CELL__px;height:__CELL__px;border-radius:14px;}
    .cap{margin-top:14px;font-size:__CAPFS__px;color:#5a4f40;text-align:center;max-width:__CAPW__px;line-height:1.3;}
    """
    css = (css.replace("__COLS__", str(cols)).replace("__TSIZE__", str(tsize))
              .replace("__CELL__", str(cell)).replace("__CAPFS__", str(cap_fs))
              .replace("__CAPW__", str(cell + 20)))
    body = f"""
      <div class="grid hand">
        <div class="head">{esc(main_title)}</div>
        {f'<div class="headsub">{esc(tail_title)}</div>' if tail_title else ''}
        <div class="sub">目的地速览</div>
        <div class="cells">{cells}</div>
      </div>"""
    return page_wrap(css, body), (1200, 1200)


# ---------------------------------------------------------------------------
# 形态 4：整趟地图海报（1080x1920，带底图 + 每日摘要）
# ---------------------------------------------------------------------------
def build_map_poster(itin, map_ref, days_map, sd):
    trip = itin.get("trip") or {}
    raw_title = trip.get("title") or "旅行手账"
    disp = re.sub(r"[（(][^）)]*[）)]\s*$", "", raw_title).strip() or raw_title
    dest = (trip.get("destination") or "").strip()
    days_n = trip.get("days") or len(days_map)
    stops_n = len([x for x in itin.get("stops", []) if x.get("name")])
    drange = ""
    if sd and days_n:
        end = sd + dt.timedelta(days=int(days_n) - 1)
        drange = f"{sd.strftime('%Y.%m.%d')} – {end.strftime('%m.%d')}"
    elif sd:
        drange = sd.strftime("%Y.%m.%d")
    travelers = trip.get("travelers") or ""
    theme = ((trip.get("theme") or "").replace("／", "/").split("/")[0]).strip()
    foot = "旅途手账" + (" · " + theme if theme else "")

    days_sorted = sorted([d for d in days_map if d])
    n = max(1, len(days_sorted))
    cols = 2 if n <= 8 else 3
    rows = (n + cols - 1) // cols
    tsize = 58 if len(disp) <= 16 else (48 if len(disp) <= 24 else 40)
    nsize = 27 if cols == 2 else 23
    # 按每格摘要的折行数估高度：中文字宽按 1、其他按 0.55，宁可略松不要压页脚
    per_line = 16 if cols == 2 else 12
    row_heights = []
    for d in days_sorted:
        names = " · ".join(x["name"] for x in days_map[d])
        width = sum(1 if ord(ch) > 127 else 0.55 for ch in names)
        lines = max(1, math.ceil(width / per_line))
        row_heights.append(30 + lines * 39 + 8)
    col_rows = [max(row_heights[i:i + cols]) for i in range(0, len(row_heights), cols)]
    days_h = sum(col_rows) + 24 * max(0, rows - 1)
    H = max(1920, 1460 + days_h + 120)

    cells = ""
    for d in days_sorted:
        names = " · ".join(x["name"] for x in days_map[d])
        accent = DAY_COLORS[(d - 1) % len(DAY_COLORS)]
        cells += (f'<div class="day"><span class="dot" style="background:{accent}"></span>'
                  f'<div><div class="dn">DAY {d}</div>'
                  f'<div class="names">{esc(names)}</div></div></div>')

    css = """
    .head{position:absolute;left:56px;right:56px;top:34px;height:260px}
    .kicker{font-size:24px;letter-spacing:8px;color:#8a7558}
    .title{font-size:__TSIZE__px;line-height:1.18;margin-top:10px}
    .meta{font-size:26px;color:#8a7558;margin-top:12px}
    .stamp{position:absolute;right:56px;top:62px;width:150px;text-align:center;
      border:2px dashed #c9b48c;border-radius:12px;padding:12px 0;transform:rotate(4deg);color:#8a7558}
    .stamp b{display:block;font-size:34px;color:#a2693a;font-weight:400}
    .stamp span{font-size:20px}
    .mapbox{position:absolute;left:0;top:300px;width:100%;height:1100px;overflow:hidden}
    .mapbox img{width:100%;height:100%;object-fit:cover;display:block}
    .mapveil{position:absolute;inset:0;
      background:linear-gradient(180deg,rgba(247,239,224,0) 74%,rgba(247,239,224,.95) 100%)}
    .rule{position:absolute;left:56px;right:56px;top:1432px;height:3px;background:#c98a4b;opacity:.45;border-radius:3px}
    .days{position:absolute;left:52px;right:52px;top:1460px;bottom:100px;display:grid;
      grid-template-columns:repeat(__COLS__,1fr);column-gap:34px;row-gap:24px;
      align-content:center}
    .day{display:flex;gap:14px;align-items:flex-start;break-inside:avoid}
    .dot{width:15px;height:15px;border-radius:50%;margin-top:10px;flex:0 0 auto}
    .dn{font-size:23px;color:#8a7558;letter-spacing:1px}
    .names{font-size:__NSIZE__px;line-height:1.4}
    .foot{position:absolute;bottom:40px;left:0;right:0;text-align:center;font-size:24px;color:#b3a081}
    """
    css = (css.replace("__TSIZE__", str(tsize)).replace("__COLS__", str(cols))
              .replace("__NSIZE__", str(nsize)))
    body = f"""
      <div class="head">
        <div class="kicker">旅 途 手 账</div>
        <div class="title">{esc(disp)}</div>
        <div class="meta">{esc(" · ".join(x for x in [drange, dest, travelers] if x))}</div>
      </div>
      <div class="stamp"><b>{days_n}</b><span>天 · {stops_n} 站</span></div>
      <div class="mapbox"><img src="{esc(map_ref)}"/><div class="mapveil"></div></div>
      <div class="rule"></div>
      <div class="days">{cells}</div>
      <div class="foot">{esc(foot)}</div>"""
    return page_wrap(css, body), (1080, H)


# ---------------------------------------------------------------------------
# 形态 5：每日地图卡（1080x1350，当日路线 + 站点时间）
# ---------------------------------------------------------------------------
def build_day_map_card(day, day_stops, sd, map_ref, trip):
    accent = DAY_COLORS[(day - 1) % len(DAY_COLORS)]
    date = day_date(sd, day)
    headline = None
    for x in day_stops:
        if "机场" not in x["name"]:
            headline = x
            break
    headline = headline or day_stops[0]
    region = headline.get("region", "")
    theme = ((trip.get("theme") or "").replace("／", "/").split("/")[0]).strip()

    rows = ""
    for x in day_stops[:6]:
        note = f'<div class="note">{esc(x["note"])}</div>' if x.get("note") else ""
        rows += (f'<div class="st"><span class="t">{esc(x.get("time") or "")}</span>'
                 f'<span class="n">{esc(x["name"])}</span></div>{note}')
    nsize = 46 if len(headline["name"]) <= 12 else (38 if len(headline["name"]) <= 18 else 32)

    css = """
    .hd{position:absolute;left:56px;right:56px;top:40px;height:150px}
    .badge{display:inline-block;background:__ACC__;color:#fff;border-radius:26px;
      padding:8px 24px;font-size:28px;letter-spacing:2px}
    .date{display:inline-block;margin-left:16px;font-size:26px;color:#8a7558}
    .headline{font-size:__NSIZE__px;line-height:1.2;margin-top:14px}
    .region{font-size:24px;color:#8a7558;margin-top:6px}
    .mapbox{position:absolute;left:0;top:236px;width:100%;height:780px;overflow:hidden}
    .mapbox img{width:100%;height:100%;object-fit:cover;display:block}
    .mapveil{position:absolute;inset:0;
      background:linear-gradient(180deg,rgba(247,239,224,0) 82%,rgba(247,239,224,.95) 100%)}
    .list{position:absolute;left:60px;right:60px;top:1046px;bottom:110px;
      display:flex;flex-direction:column;justify-content:center}
    .st{font-size:28px;margin-bottom:12px}
    .st .t{color:__ACC__;margin-right:14px;font-variant-numeric:tabular-nums}
    .st .n{color:#4a4036}
    .note{font-size:21px;color:#9a8360;margin:-6px 0 12px 74px;line-height:1.4}
    .foot{position:absolute;bottom:34px;left:0;right:0;text-align:center;font-size:22px;color:#b3a081}
    """
    css = css.replace("__ACC__", accent).replace("__NSIZE__", str(nsize))
    body = f"""
      <div class="hd">
        <div><span class="badge">DAY {day}</span><span class="date">{esc(date)}</span></div>
        <div class="headline">{esc(headline["name"])}</div>
        <div class="region">{esc(region)}</div>
      </div>
      <div class="mapbox"><img src="{esc(map_ref)}"/><div class="mapveil"></div></div>
      <div class="list">{rows}</div>
      <div class="foot">{esc("旅途手账" + (" · " + theme if theme else ""))}</div>"""
    return page_wrap(css, body), (1080, 1350)


# ---------------------------------------------------------------------------
# 形态 6：金句卡片（竖版 1080x1350）
# ---------------------------------------------------------------------------
def build_quote(itin, idx, illu_dir):
    trip = itin.get("trip") or {}
    accent = DAY_COLORS[idx % len(DAY_COLORS)]
    quote = QUOTES[idx % len(QUOTES)]
    # 轮换使用可用插画（含封面）
    avail = []
    cov = cover_path(illu_dir)
    if cov:
        avail.append(cov)
    # 顺带收集站点插画
    if illu_dir:
        for p in sorted(illu_dir.glob("*.png")):
            if p.name == "cover.png":
                continue
            avail.append(_img_ref(p))
    src = avail[idx % len(avail)] if avail else None

    css = """
    .qc{position:relative;width:100%;height:100%;}
    .top{position:relative;width:100%;height:760px;}
    .top img,.top .ph{width:100%;height:760px;}
    .tape.q{top:24px;left:50%;margin-left:-60px;transform:rotate(-3deg);}
    .bottom{height:590px;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:0 90px;text-align:center;}
    .mark{font-size:34px;color:__ACC__;margin-bottom:26px;letter-spacing:4px;}
    .quote{font-size:58px;color:#3f362b;line-height:1.5;}
    .sign{margin-top:34px;font-size:28px;color:#9a8360;}
    """
    css = css.replace("__ACC__", accent)
    body = f"""
      <div class="tape q"></div>
      <div class="qc hand">
        <div class="top">{render_img(src, w=1080, h=760)}</div>
        <div class="bottom">
          <div class="mark">✎ 旅途手账</div>
          <div class="quote">{esc(quote)}</div>
          <div class="sign">—— {esc((trip.get('destination') or '旅行').split(' ')[0])}</div>
        </div>
      </div>"""
    return page_wrap(css, body), (1080, 1350)


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------
def launch_browser(playwright):
    attempts = [
        ({"channel": "chrome"}, "系统 Chrome"),
        ({"channel": "msedge"}, "系统 Edge"),
        ({}, "playwright Chromium"),
    ]
    last = None
    for kwargs, label in attempts:
        try:
            return playwright.chromium.launch(**kwargs), label
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"无法启动浏览器：{last}")


# 渲染后自检：文字溢出画布 / 页脚压住站点列表 / 图片加载失败 / 插画占位
CHECK_JS = """() => {
  const frame = document.querySelector('.frame');
  if (!frame) return { fatal: '缺少 .frame 容器' };
  const fr = frame.getBoundingClientRect();
  const tol = 2;
  const over = [];
  const sel = '.title,.stamp-dest,.stamp-sub,.quote,.head,.cap,.kw,.sub,.meta,'
            + '.date,.foot,.badge,.kicker,.mark,.sign,.headline,.region,'
            + '.dn,.names,.st,.list,.mapbox';
  document.querySelectorAll(sel).forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.bottom > fr.bottom + tol) {
      over.push((el.className || el.tagName) + ' 下溢出 ' + Math.round(r.bottom - fr.bottom) + 'px');
    }
    if (r.right > fr.right + tol) {
      over.push((el.className || el.tagName) + ' 右溢出 ' + Math.round(r.right - fr.right) + 'px');
    }
  });
  const foot = document.querySelector('.foot');
  let footOverlap = false;
  if (foot) {
    const fa = foot.getBoundingClientRect();
    document.querySelectorAll('.kws,.days,.list,.cells').forEach(el => {
      if (el.getBoundingClientRect().bottom > fa.top + 1) footOverlap = true;
    });
  }
  const broken = Array.from(document.images)
    .filter(i => i.complete && i.naturalWidth === 0)
    .map(i => decodeURIComponent((i.getAttribute('src') || '').split('/').pop()));
  return {
    overflow: over,
    footOverlap: footOverlap,
    broken: broken,
    placeholders: document.querySelectorAll('.ph').length,
    images: document.images.length
  };
}"""


def render_batch(jobs):
    """一次浏览器会话渲染全部页面，同时采集自检数据。

    jobs: [{name, html, png, w, h}]
    返回 (engine|None, results|{name: dict}, error|str)
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None, {}, "未安装 playwright，跳过 PNG（HTML 已生成，可手动打开）"
    try:
        with sync_playwright() as p:
            browser, label = launch_browser(p)
            results = {}
            for job in jobs:
                page = browser.new_page(
                    viewport={"width": job["w"], "height": job["h"]},
                    device_scale_factor=SCALE,
                )
                try:
                    page.goto("file://" + str(job["html"]))
                    page.wait_for_timeout(400)
                    page.screenshot(path=str(job["png"]))
                    results[job["name"]] = page.evaluate(CHECK_JS)
                except Exception as e:  # noqa: BLE001
                    results[job["name"]] = {"fatal": str(e)}
                finally:
                    page.close()
            browser.close()
            return label, results, ""
    except Exception as e:  # noqa: BLE001
        return None, {}, str(e)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="无地图分享图生成器")
    ap.add_argument("itinerary", help="itinerary.json 路径")
    ap.add_argument("--out", help="输出目录（默认 <itinerary 同目录>/share）")
    ap.add_argument("--types", default="all",
                    help="all|day,cover,grid,quote,map,mapday（逗号分隔；all 含 map，不含 mapday）")
    ap.add_argument("--skip-verify", action="store_true", help="跳过渲染后自检")
    args = ap.parse_args()

    itin_path = Path(args.itinerary).resolve()
    itin = load_itin(itin_path)
    trip_dir = itin_path.parent
    illu_dir = trip_dir / "illustrations"
    out_dir = Path(args.out).resolve() if args.out else (trip_dir / "share")
    out_dir.mkdir(parents=True, exist_ok=True)
    global _HTML_DIR
    _HTML_DIR = out_dir  # 插画按相对本目录引用，--out 指到别处也能加载

    sd = start_date(itin)
    stops = itin.get("stops", [])
    # 按天分组
    days_map = {}
    for s in stops:
        days_map.setdefault(s.get("day", 0), []).append(s)

    types = [t.strip() for t in args.types.split(",") if t.strip()]
    allowed = ("all", "day", "cover", "grid", "quote", "map", "mapday")
    unknown = [t for t in types if t not in allowed]
    if unknown:
        ap.error(f"未知的 --types: {', '.join(unknown)}（可选 {'|'.join(allowed)}）")
    if "all" in types:
        # all 默认带一张整趟地图海报；每日地图卡更耗时，需显式指定 mapday
        types = ["day", "cover", "grid", "map", "quote"]

    jobs = []

    def do(html, size, name):
        hp = out_dir / (name + ".html")
        hp.write_text(html, encoding="utf-8")
        jobs.append({"name": name, "html": hp, "png": out_dir / (name + ".png"),
                     "w": size[0], "h": size[1]})

    if "day" in types:
        max_day = max([d for d in days_map if d] or [0])
        for d in range(1, max_day + 1):
            if d not in days_map:
                continue
            html, size = build_daily_poster(d, days_map[d], sd, illu_dir, trip=itin.get("trip") or {})
            do(html, size, f"day_{d:02d}")

    if "cover" in types:
        html, size = build_cover(itin, illu_dir)
        do(html, size, "cover_hero")

    if "grid" in types:
        html, size = build_grid(itin, stops, illu_dir)
        do(html, size, "grid")

    if "quote" in types:
        for i in range(3):
            html, size = build_quote(itin, i, illu_dir)
            do(html, size, f"quote_{i + 1:02d}")

    # ---- 地图版（B 整趟海报 / C 每日地图卡）：先渲染地图快照，再套分享图版式 ----
    shots = []
    if "map" in types:
        shots.append({"name": "poster", "w": 1080, "h": 1100,
                      "key_names": key_map_labels(stops)})
    if "mapday" in types:
        for d in sorted([x for x in days_map if x]):
            shots.append({"name": f"day{d:02d}", "w": 1080, "h": 780, "days": [d]})

    refs, map_engine, map_err = ({}, None, "")
    if shots:
        refs, map_engine, map_err = render_map_shots(itin, shots, out_dir)
    if map_engine:
        print(f"ℹ️ 地图快照引擎: {map_engine}")
    if map_err:
        print(f"⚠️ 地图快照失败，跳过地图版：{map_err}")

    if "map" in types and refs.get("poster"):
        html, size = build_map_poster(itin, refs["poster"], days_map, sd)
        do(html, size, "map_poster")
    if "mapday" in types:
        for d in sorted([x for x in days_map if x]):
            ref = refs.get(f"day{d:02d}")
            if not ref:
                continue
            html, size = build_day_map_card(d, days_map[d], sd, ref, itin.get("trip") or {})
            do(html, size, f"map_day_{d:02d}")

    engine, results, render_err = render_batch(jobs)

    print(f"\n✅ 无地图分享图已生成 → {out_dir}")
    for job in jobs:
        mark = "✅" if job["png"].exists() else "⚠️"
        print(f"   {mark} {job['png']}")

    if engine is None:
        print(f"\n⚠️ 跳过自检：{render_err}")
        return 0
    if args.skip_verify:
        print(f"\n⚠️ 已跳过自检（--skip-verify），渲染引擎: {engine}")
        return 0

    print(f"\n--- 分享图自检（{engine}）---")
    fails, warns = [], []
    for job in jobs:
        name = job["name"]
        r = results.get(name)
        if not r:
            print(f"  ⚠️ {name}: 未取到自检数据")
            warns.append(name)
            continue
        if r.get("fatal"):
            print(f"  ❌ {name}: 渲染异常 {r['fatal']}")
            fails.append(name)
            continue
        issues = []
        if r.get("overflow"):
            issues.append("文字溢出画布：" + "；".join(r["overflow"][:3]))
        if r.get("footOverlap"):
            issues.append("页脚压住了站点列表")
        if r.get("broken"):
            issues.append("图片加载失败：" + "、".join(r["broken"][:3]))
        if issues:
            print(f"  ❌ {name}: " + " / ".join(issues))
            fails.append(name)
            continue
        notes = []
        if r.get("placeholders"):
            notes.append(f"插画缺失 {r['placeholders']} 张（已用占位纸卡）")
        if name == "grid" and r.get("images", 0) < 2:
            notes.append("可用插画不足 2 张，九宫格参考价值低")
        if notes:
            print(f"  ⚠️ {name}: " + " / ".join(notes))
            warns.append(name)
        else:
            print(f"  ✅ {name}")

    passed = len(jobs) - len(fails) - len(warns)
    print(f"\n{'✅' if not fails else '❌'} 自检：{passed} 张通过，"
          f"{len(warns)} 张告警，{len(fails)} 张失败")
    if fails:
        print("   请修复上方 ❌ 项后重跑，不要带着文字溢出/图片失败的图交付。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
