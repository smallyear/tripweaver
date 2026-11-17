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
import sys
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


def illu_path(illu_dir, name):
    """返回相对于 HTML 文件的插画引用路径；不存在返回 None。

    磁盘文件用中文真名（<站名>.png），HTML 里用 encodeURIComponent 引用，
    浏览器加载 file:// 时会解码回中文，正好匹配磁盘文件。
    """
    if not illu_dir:
        return None
    import urllib.parse
    if (illu_dir / (name + ".png")).exists():
        return "../illustrations/" + urllib.parse.quote(name, safe="") + ".png"
    return None


def cover_path(illu_dir):
    if illu_dir and (illu_dir / "cover.png").exists():
        return "../illustrations/cover.png"
    return None


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
    .poster{position:relative;width:1080px;height:1440px;padding:64px 60px;}
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
    .hero{position:relative;width:1600px;height:1000px;}
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
    for s in stops:
        name = s["name"]
        p = illu_path(illu_dir, name)
        if p:
            items.append((p, name))
    n = len(items)
    # 列数：1→1,2→2,3→3,≥4→3（保持方感）
    cols = 1 if n <= 1 else (2 if n == 2 else 3)
    cells = ""
    for p, name in items:
        cells += f"""
          <div class="cell">
            {render_img(p, w=320, h=320)}
            <div class="cap hand">{esc(name)}</div>
          </div>"""
    if not cells:
        cells = '<div class="cap hand" style="font-size:40px;color:#a08b66;">（暂无插画，先给站点生成插画）</div>'

    css = """
    .grid{position:relative;width:1200px;height:1200px;padding:70px 60px;display:flex;flex-direction:column;}
    .head{text-align:center;font-size:56px;color:#3f362b;margin-bottom:8px;}
    .sub{text-align:center;font-size:28px;color:#8a7558;margin-bottom:34px;}
    .cells{display:grid;grid-template-columns:repeat(__COLS__,1fr);gap:30px;justify-items:center;align-content:center;flex:1;}
    .cell{display:flex;flex-direction:column;align-items:center;}
    .cell img,.cell .ph{width:320px;height:320px;border-radius:14px;}
    .cap{margin-top:14px;font-size:26px;color:#5a4f40;text-align:center;max-width:340px;}
    """
    css = css.replace("__COLS__", str(cols))
    body = f"""
      <div class="grid hand">
        <div class="head">{esc(title)}</div>
        <div class="sub">目的地速览</div>
        <div class="cells">{cells}</div>
      </div>"""
    return page_wrap(css, body), (1200, 1200)


# ---------------------------------------------------------------------------
# 形态 4：金句卡片（竖版 1080x1350）
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
    import urllib.parse
    if illu_dir:
        for p in sorted(illu_dir.glob("*.png")):
            if p.name == "cover.png":
                continue
            avail.append("../illustrations/" + p.name)
    src = avail[idx % len(avail)] if avail else None

    css = """
    .qc{position:relative;width:1080px;height:1350px;}
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


def render(html_path, png_path, w, h):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False, "未安装 playwright，跳过 PNG（HTML 已生成）"
    try:
        with sync_playwright() as p:
            browser, _ = launch_browser(p)
            page = browser.new_page(viewport={"width": w, "height": h},
                                    device_scale_factor=SCALE)
            page.goto("file://" + str(html_path))
            page.wait_for_timeout(400)
            page.screenshot(path=str(png_path))
            browser.close()
        return True, ""
    except Exception as e:  # noqa: BLE001
        return False, str(e)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="无地图分享图生成器")
    ap.add_argument("itinerary", help="itinerary.json 路径")
    ap.add_argument("--out", help="输出目录（默认 <itinerary 同目录>/share）")
    ap.add_argument("--types", default="all",
                    help="all|day,cover,grid,quote（逗号分隔）")
    args = ap.parse_args()

    itin_path = Path(args.itinerary).resolve()
    itin = load_itin(itin_path)
    trip_dir = itin_path.parent
    illu_dir = trip_dir / "illustrations"
    out_dir = Path(args.out).resolve() if args.out else (trip_dir / "share")
    out_dir.mkdir(parents=True, exist_ok=True)

    sd = start_date(itin)
    stops = itin.get("stops", [])
    # 按天分组
    days_map = {}
    for s in stops:
        days_map.setdefault(s.get("day", 0), []).append(s)

    types = [t.strip() for t in args.types.split(",") if t.strip()]
    if "all" in types:
        types = ["day", "cover", "grid", "quote"]

    produced = []
    errors = []

    def do(html, size, name):
        hp = out_dir / (name + ".html")
        pp = out_dir / (name + ".png")
        hp.write_text(html, encoding="utf-8")
        ok, msg = render(hp, pp, *size)
        if ok and pp.exists():
            produced.append(str(pp))
        else:
            errors.append(f"{name}: {msg or 'PNG 未生成'}")

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

    print(f"\n✅ 无地图分享图已生成 → {out_dir}")
    for f in produced:
        print("   " + f)
    if errors:
        print("\n⚠️ 以下未成功：")
        for e in errors:
            print("   " + e)
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
