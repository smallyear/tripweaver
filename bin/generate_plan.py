#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""读取 itinerary.json，渲染单文件方案书 plan.html（可选导出 plan.pdf）。

用法:
    python3 generate_plan.py <itinerary.json> [--out <目录>] [--checklist checklist.json]
                             [--weather weather.json] [--no-embed] [--pdf] [--skip-verify]

- 纯静态 HTML：不联网、不调模型、不需要 playwright。图片默认 base64 内嵌 → 单文件可发微信/离线打开。
- 七节：摘要 / 目的地调研 / 天气研判 / 逐日行程 / 路线图与动线 / 预算明细 / 出行清单。
- 数据全部来自文件：itinerary.json（必需）+ checklist.json + weather.json + route_map.png + illustrations/。
- 自检：占位符残留 / 站点渲染数不符 / 预算合计与手写合计不符 / 内嵌图片读取失败 → 退出码 1。
"""
import argparse
import base64
import html
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_checklist import THEME_BAR, THEME_CSS, THEME_JS  # noqa: E402

WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
CAT_ORDER = ["大交通", "住宿", "门票", "市内交通", "餐饮", "其他"]
MISSING = []   # 降级项（⚠️）
FATAL = []     # 阻断项（❌）


def esc(t):
    return html.escape("" if t is None else str(t), quote=True)


def money(n):
    try:
        return f"¥{float(n):,.0f}"
    except (TypeError, ValueError):
        return "—"


def _compress_data_uri(p, max_w=1000, quality=82):
    """把图片降采样并转 JPEG 后再内嵌：地图海报原图可达 4MB，直接 base64 会变成 5MB 的单文件。

    优先用 macOS 自带 sips（无额外依赖）；没有 sips 或转换失败则返回 None，退回原图内嵌。
    """
    if not shutil.which("sips"):
        return None
    tmp = None
    try:
        fd, name = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        tmp = Path(name)
        subprocess.run(
            ["sips", "-Z", str(max_w), "-s", "format", "jpeg",
             "-s", "formatOptions", str(quality), str(p), "--out", str(tmp)],
            check=True, capture_output=True, timeout=60,
        )
        if tmp.stat().st_size == 0:
            return None
        return "data:image/jpeg;base64," + base64.b64encode(tmp.read_bytes()).decode("ascii")
    except Exception:  # noqa: BLE001
        return None
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def img_data(path, fatal_on_read_error=True):
    """把图片转成 data URI；缺失返回 None（降级），读取失败记 ❌。"""
    p = Path(path)
    if not p.exists():
        return None
    if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
        compressed = _compress_data_uri(p)
        if compressed:
            return compressed
    try:
        ext = p.suffix.lower().lstrip(".") or "png"
        mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp", "svg": "svg+xml"}.get(ext, ext)
        return f"data:image/{mime};base64," + base64.b64encode(p.read_bytes()).decode("ascii")
    except Exception as e:  # noqa: BLE001
        if fatal_on_read_error:
            FATAL.append(f"内嵌图片读取失败：{p.name}（{e}）")
        return None


def parse_days(itin):
    trip = itin.get("trip", {})
    days = trip.get("days")
    if days:
        return int(days)
    stops = itin.get("stops") or []
    return max([int(s.get("day", 1)) for s in stops], default=1)


def trip_dates(itin):
    trip = itin.get("trip", {})
    raw = trip.get("start_date")
    if not raw:
        return None, None
    try:
        sd = datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None, None
    return sd, sd + timedelta(days=parse_days(itin) - 1)


def pax_count(trip):
    b = trip.get("budget")
    if isinstance(b, dict) and b.get("pax"):
        try:
            return int(b["pax"])
        except (TypeError, ValueError):
            pass
    for ch in str(trip.get("travelers") or ""):
        if ch.isdigit():
            n = int(ch)
            if 1 <= n <= 40:
                return n
    return None


def budget_view(budget, travelers):
    """把 trip.budget 归一成可渲染的结构；字符串按旧版兼容处理。"""
    if not budget:
        return None
    if isinstance(budget, str):
        return {"legacy": budget}
    items = [it for it in (budget.get("items") or []) if it]
    if not items:
        return {"legacy": budget.get("basis") or budget.get("total") or "—"}
    pct = budget.get("contingency_pct", 10)
    try:
        pct = float(pct)
    except (TypeError, ValueError):
        pct = 10.0
    subtotal = 0.0
    rows = []
    for it in items:
        try:
            amt = float(it.get("amount") or 0)
        except (TypeError, ValueError):
            amt = 0.0
        subtotal += amt
        rows.append({
            "cat": str(it.get("cat") or "其他"),
            "detail": it.get("detail") or "",
            "amount": amt,
            "note": it.get("note") or "",
        })
    rows.sort(key=lambda r: (CAT_ORDER.index(r["cat"]) if r["cat"] in CAT_ORDER else len(CAT_ORDER), r["cat"]))
    contingency = subtotal * pct / 100.0
    total = subtotal + contingency
    pax = pax_count({"budget": budget, "travelers": travelers})
    stated = budget.get("total")
    if stated is not None:
        try:
            if abs(float(stated) - total) > 1:
                FATAL.append(f"预算合计不符：明细+弹性 = {total:.0f}，手写 total = {float(stated):.0f}")
        except (TypeError, ValueError):
            pass
    return {
        "rows": rows,
        "subtotal": subtotal,
        "pct": pct,
        "contingency": contingency,
        "total": total,
        "pax": pax,
        "per_person": (total / pax) if pax else None,
        "basis": budget.get("basis") or "",
        "currency": budget.get("currency") or "CNY",
    }


# ---------------------------------------------------------------- 各节渲染

def render_header(trip, sd, ed):
    days = parse_days({"trip": trip})
    facts = [
        ("行程日期", f"{sd.isoformat()} → {ed.isoformat()}（{days} 天）" if sd and ed else "—"),
        ("同行人", trip.get("travelers") or "—"),
        ("节奏", trip.get("pace") or "—"),
        ("主题", trip.get("theme") or "—"),
        ("预算口径", (trip.get("budget") or {}).get("basis") if isinstance(trip.get("budget"), dict) else (trip.get("budget") or "—")),
    ]
    facts_html = "".join(
        f'<div class="fact"><div class="k">{esc(k)}</div><div class="v">{esc(v)}</div></div>'
        for k, v in facts if v and v != "—" or k in ("同行人", "行程日期")
    )
    info_date = trip.get("info_date")
    badge = (
        f'<div class="badge">信息基准日 <b>{esc(info_date)}</b> · 价格/时间/政策均以该日检索为准，出发前请复核</div>'
        if info_date else
        '<div class="badge muted">未标注信息基准日：价格与开放时间请在出发前自行复核</div>'
    )
    return f"""
<header class="cover">
  <div class="kicker">TRAVEL PLAN · 旅行方案</div>
  <h1>{esc(trip.get('title') or '旅行方案')}</h1>
  <div class="sub">{esc(trip.get('destination') or '')}</div>
  <div class="facts">{facts_html}</div>
  {badge}
</header>"""


def render_research(blocks):
    blocks = [b for b in (blocks or []) if b]
    if not blocks:
        MISSING.append("目的地调研（trip.research 为空，本节省略）")
        return ""
    out = []
    for b in blocks:
        title = esc(b.get("title") or "调研")
        items = "".join(f"<li>{esc(i)}</li>" for i in (b.get("items") or []))
        table_html = ""
        table = b.get("table")
        if isinstance(table, dict) and table.get("head"):
            head = "".join(f"<th>{esc(h)}</th>" for h in table["head"])
            rows = "".join(
                "<tr>" + "".join(f"<td>{esc(c)}</td>" for c in r) + "</tr>"
                for r in (table.get("rows") or [])
            )
            table_html = f'<div class="tbl-wrap"><table class="data"><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div>'
        src = []
        if b.get("source"):
            src.append(f"来源：{esc(b['source'])}")
        if b.get("date"):
            src.append(f"信息月份：{esc(b['date'])}")
        src_html = f'<div class="src">{" · ".join(src)}</div>' if src else ""
        out.append(
            f'<div class="block"><h3>{title}</h3>'
            + (f'<ul class="items">{items}</ul>' if items else "")
            + table_html + src_html + "</div>"
        )
    return f'<section id="research"><h2>目的地调研</h2>{"".join(out)}</section>'


def load_json(path):
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        MISSING.append(f"{p.name} 解析失败（{e}），对应章节降级")
        return None


def render_weather(weather, trip):
    impacts = trip.get("day_impacts") or {}
    climate = trip.get("climate_note") or ""
    if not weather:
        MISSING.append("实时气象（缺 weather.json，先跑 generate_weather.py）")
        return (
            '<section id="weather"><h2>天气研判</h2>'
            '<div class="hint">本次未取到实时预报。先运行 '
            '<code>bin/generate_weather.py &lt;itinerary.json&gt;</code> 生成 weather.json，'
            '再重跑本脚本即可补上逐日天气；单独查看请打开 weather.html。</div></section>'
        )
    cards = weather.get("cards") or []
    tips = weather.get("tips") or []
    dash = "<span class='muted'>—</span>"
    rows = []
    for c in cards:
        day = c.get("day")
        impact = impacts.get(str(day)) or impacts.get(day) or ""
        if c.get("available"):
            rows.append(
                f"<tr><td class='nowrap'>Day {esc(day)}<br><span class='muted'>{esc(c.get('date',''))} {esc(c.get('weekday',''))}</span></td>"
                f"<td>{esc(c.get('emoji',''))} {esc(c.get('desc',''))}</td>"
                f"<td class='nowrap'>{esc(c.get('tmin'))}° ~ {esc(c.get('tmax'))}°C</td>"
                f"<td class='nowrap'>{esc(c.get('rain'))}%</td>"
                f"<td>{esc(impact) or dash}</td></tr>"
            )
        else:
            rows.append(
                f"<tr class='nodata'><td class='nowrap'>Day {esc(day)}<br><span class='muted'>{esc(c.get('date',''))} {esc(c.get('weekday',''))}</span></td>"
                f"<td class='muted'>临近再查（超出 16 天预报窗口）</td><td>—</td><td>—</td>"
                f"<td>{esc(impact) or dash}</td></tr>"
            )
    tips_html = "".join(f"<li>{esc(t)}</li>" for t in tips)
    climate_html = f'<p class="climate">{esc(climate)}</p>' if climate else ""
    note = weather.get("generated") or ""
    return f"""
<section id="weather"><h2>天气研判</h2>
  {climate_html}
  <div class="tbl-wrap"><table class="data weather">
    <thead><tr><th>日期</th><th>天气</th><th>温度</th><th>降水</th><th>对当日行程的影响</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table></div>
  {f'<ul class="tips">{tips_html}</ul>' if tips_html else ''}
  <div class="src">数据来源：Open-Meteo 实时预报{f' · 取数于 {esc(note)}' if note else ''} · 出发前 1–2 天请再看一次</div>
</section>"""


def render_days(itin):
    trip = itin.get("trip", {})
    stops = [s for s in (itin.get("stops") or []) if s and s.get("name")]
    sd, _ = trip_dates(itin)
    themes = trip.get("day_themes") or {}
    by_day = {}
    for s in stops:
        try:
            d = int(s.get("day", 1))
        except (TypeError, ValueError):
            d = 1
        by_day.setdefault(d, []).append(s)
    out = []
    for d in sorted(by_day):
        theme = themes.get(str(d)) or themes.get(d) or ""
        date_line = ""
        if sd:
            cur = sd + timedelta(days=d - 1)
            date_line = f"{cur.isoformat()} {WEEKDAYS[cur.weekday()]}"
        items = []
        for s in by_day[d]:
            facts = s.get("facts") or []
            facts_html = ""
            if facts:
                facts_html = '<ul class="facts">' + "".join(
                    f"<li><span class='fk'>{esc(f.get('k',''))}</span> {esc(f.get('v',''))}"
                    + (f"<span class='fsrc'>（{esc(f.get('src',''))}{' ' + esc(f.get('date','')) if f.get('date') else ''}）</span>" if f.get("src") else "")
                    + "</li>" for f in facts
                ) + "</ul>"
            alt = s.get("alt")
            alt_html = f'<div class="alt"><span class="tag">备选</span>{esc(alt)}</div>' if alt else ""
            items.append(
                f'<li class="stop"><div class="t">{esc(s.get("time") or "")}</div>'
                f'<div class="body"><div class="n">{esc(s["name"])}</div>'
                + (f'<div class="note">{esc(s["note"])}</div>' if s.get("note") else "")
                + facts_html + alt_html + "</div></li>"
            )
        out.append(
            f'<div class="day"><div class="dayhead"><span class="dnum">D{d}</span>'
            f'<span class="dtheme">{esc(theme) or "行程"}</span>'
            f'<span class="ddate">{esc(date_line)}</span></div>'
            f'<ul class="timeline">{"".join(items)}</ul></div>'
        )
    if not out:
        FATAL.append("逐日行程为空（stops 里没有带 name 的站点）")
        return ""
    return f'<section id="days"><h2>逐日行程</h2>{"".join(out)}</section>'


def render_route(itin, asset_dirs, embed):
    stops = [s for s in (itin.get("stops") or []) if s and s.get("name")]
    by_day = {}
    for s in stops:
        try:
            d = int(s.get("day", 1))
        except (TypeError, ValueError):
            d = 1
        by_day.setdefault(d, []).append(s)
    lines = []
    for d in sorted(by_day):
        names = " → ".join(esc(s["name"]) for s in by_day[d])
        lines.append(f'<li><b>D{d}</b>：{names}</li>')
    # 内嵌的用「地图海报」（share/map_poster.png，纯地图+每日一行摘要）；
    # 不用 route_map.png——那是「地图置顶+行程双栏」整图，与下文逐日行程重复，且动辄 2–3MB。
    candidates = [Path(d) / "share" / "map_poster.png" for d in asset_dirs] + [Path(d) / "share" / "_map_poster.png" for d in asset_dirs]
    poster = next((p for p in candidates if p.exists()), None)
    if poster and embed:
        data = img_data(poster)
        if data:
            fig = (f'<figure><img src="{data}" alt="全程路线图"/>'
                   f'<figcaption>{esc(itin.get("trip", {}).get("title") or "行程")} · 全程路线图</figcaption></figure>')
        else:
            MISSING.append("路线图（地图海报读取失败）")
            fig = '<div class="hint">地图海报读取失败，可打开 travel_map.html 查看交互地图。</div>'
    elif poster:
        rel = os.path.relpath(poster, asset_dirs[0])
        fig = f'<figure><img src="{esc(rel)}" alt="全程路线图"/></figure>'
    else:
        MISSING.append("路线图（缺 share/map_poster.png，用占位提示）")
        fig = ('<div class="hint">尚未生成全程地图海报。跑 <code>bin/generate_share.py &lt;itinerary.json&gt; --types map</code> '
               '后重跑本脚本即可补上；也可先看下方每日动线，或打开 travel_map.html 看交互地图。</div>')
    map_link = '<div class="srcline">交互地图（可缩放、点站点联动）：打开 <code>travel_map.html</code></div>'
    return f"""
<section id="route"><h2>路线图与每日动线</h2>
  {fig}
  <ul class="daysflow">{''.join(lines)}</ul>
  {map_link}
  <div class="src">示意图，以实时导航为准；动线按站点顺序生成，若临时调换顺序请以实际路况为准。</div>
</section>"""


def render_budget(bv, trip):
    if not bv:
        MISSING.append("预算明细（trip.budget 缺失）")
        return ""
    if bv.get("legacy"):
        return (
            '<section id="budget"><h2>预算明细</h2>'
            f'<p class="climate">预算：{esc(bv["legacy"])}</p>'
            '<div class="hint">当前只有总预算数字。若要分项表，请在 itinerary.json 里把 '
            '<code>trip.budget</code> 写成对象（见 references/plan-doc-guide.md）。</div></section>'
        )
    rows, last_cat = [], None
    for r in bv["rows"]:
        cat_cell = f'<td class="cat">{esc(r["cat"])}</td>' if r["cat"] != last_cat else '<td class="cat"></td>'
        last_cat = r["cat"]
        rows.append(
            f'<tr>{cat_cell}<td>{esc(r["detail"])}</td>'
            f'<td class="num">{money(r["amount"])}</td><td class="note">{esc(r["note"])}</td></tr>'
        )
    pax = bv.get("pax")
    per_person = (
        f'<tr><td class="cat">人均</td><td>含弹性合计 ÷ {pax} 人</td>'
        f'<td class="num">{money(bv["per_person"])}</td><td class="note"></td></tr>'
        if bv.get("per_person") else ""
    )
    pct = bv["pct"]
    pct_label = f"{pct:g}%"
    return f"""
<section id="budget"><h2>预算明细</h2>
  <div class="tbl-wrap"><table class="data money">
    <thead><tr><th>分项</th><th>明细</th><th class="num">金额</th><th>备注</th></tr></thead>
    <tbody>
      {''.join(rows)}
      <tr class="sum"><td class="cat">小计</td><td>分项之和</td><td class="num">{money(bv["subtotal"])}</td><td class="note">不含弹性</td></tr>
      <tr class="sum"><td class="cat">弹性</td><td>预留 {pct_label}</td><td class="num">{money(bv["contingency"])}</td><td class="note">应急/临时加项</td></tr>
      <tr class="total"><td class="cat">合计</td><td>含 {pct_label} 弹性</td><td class="num">{money(bv["total"])}</td><td class="note">{esc(bv.get("basis") or "")}</td></tr>
      {per_person}
    </tbody>
  </table></div>
  <div class="src">价格按官方/主流价计；多来源冲突时区间写在备注，实际以当日官方为准。儿童/老人按优惠政策预估，现场可能需证件核验。</div>
</section>"""


def render_checklist(cl, doc_link=True):
    if not cl:
        MISSING.append("出行清单（缺 checklist.json）")
        return (
            '<section id="checklist"><h2>出行清单</h2>'
            '<div class="hint">本次未生成清单。运行 <code>bin/generate_checklist.py</code> 后重跑本脚本，'
            '或用 checklist.html 单独勾选。</div></section>'
        )
    meta = cl.get("meta") or {}
    timeline = cl.get("timeline") or []
    cats = cl.get("categories") or {}
    notes = cl.get("notes") or []
    tl_html = ""
    for b in timeline:
        items = "".join(
            f'<li><label class="ck"><input type="checkbox"/><span>{esc(i)}</span></label></li>'
            for i in (b.get("items") or [])
        )
        tl_html += f'<div class="bucket"><div class="lead">{esc(b.get("lead"))}</div><ul>{items}</ul></div>'
    cards = ""
    for key, c in cats.items():
        if not c:
            continue
        items = "".join(
            f'<li><label class="ck"><input type="checkbox"/><span>{esc(i)}</span></label></li>'
            for i in (c.get("items") or [])
        )
        cards += (
            f'<div class="card"><div class="ctitle">{esc(c.get("title") or key)}</div>'
            + (f'<div class="csum">{esc(c.get("summary"))}</div>' if c.get("summary") else "")
            + f'<ul class="items">{items}</ul></div>'
        )
    notes_html = "".join(f"<li>{esc(n)}</li>" for n in notes)
    head = " · ".join(esc(x) for x in [meta.get("season"), meta.get("transport")] if x)
    link = (
        '<div class="srcline">需要单独勾选或打印，可打开 <code>checklist.html</code>（勾选状态本地保存）。</div>'
        if doc_link else ""
    )
    return f"""
<section id="checklist"><h2>出行清单</h2>
  {f'<div class="src">{head}</div>' if head else ''}
  {f'<div class="sub2">提前办理时间线</div><div class="tl">{tl_html}</div>' if tl_html else ''}
  {f'<div class="grid">{cards}</div>' if cards else ''}
  {f'<ul class="notes">{notes_html}</ul>' if notes_html else ''}
  {link}
</section>"""


def render_footer(trip, weather):
    info = trip.get("info_date") or "未标注"
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""
<footer>
  <div>信息基准日：{esc(info)} ｜ 本方案生成于 {esc(stamp)}</div>
  <div>价格、开放时间与预约政策均以检索当日为准，出发前请复核；天气数据来自 Open-Meteo，出发前 1–2 天再看一次。</div>
  <div>本方案不代订机票/酒店/门票，不代办签证与保险。</div>
</footer>"""


PAGE_CSS = """
* { box-sizing: border-box; }
body { margin: 0; padding: 26px 16px 70px; background: #f4f6f9; color: #1f2933;
       font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; line-height: 1.65; }
.page { max-width: 940px; margin: 0 auto; background: #fff; border-radius: 16px;
        box-shadow: 0 2px 14px rgba(0,0,0,.07); padding: 40px 44px 32px; }
.cover { border-bottom: 2px solid #eef1f5; padding-bottom: 22px; margin-bottom: 8px; }
.kicker { font-size: 11px; letter-spacing: .18em; color: #9aa6b2; margin-bottom: 8px; }
.cover h1 { font-size: 30px; margin: 0 0 6px; line-height: 1.3; overflow-wrap: break-word; }
.cover .sub { font-size: 15px; color: #5b6b7c; margin-bottom: 18px; }
.facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; }
.fact { background: #f8fafc; border: 1px solid #edf1f6; border-radius: 10px; padding: 10px 12px; }
.fact .k { font-size: 11px; color: #8a97a5; margin-bottom: 2px; }
.fact .v { font-size: 14px; font-weight: 600; }
.badge { margin-top: 14px; font-size: 12.5px; color: #6b5a33; background: #fdf6e6;
         border: 1px solid #f0e0bc; border-radius: 8px; padding: 8px 12px; }
.badge.muted { color: #7b8794; background: #f6f7f9; border-color: #e6eaef; }
h2 { font-size: 20px; margin: 34px 0 14px; padding-left: 12px; border-left: 5px solid #4361ee;
     counter-increment: none; }
h3 { font-size: 15.5px; margin: 0 0 8px; }
section { margin-bottom: 6px; }
.block { border: 1px solid #e6ebf1; border-radius: 10px; padding: 14px 16px; margin-bottom: 12px; background: #fcfdff; }
ul.items, ul.tips, ul.notes, ul.daysflow { margin: 0; padding-left: 20px; }
ul.items li, ul.tips li, ul.notes li { margin: 4px 0; font-size: 14px; }
ul.daysflow { padding-left: 18px; }
ul.daysflow li { font-size: 14px; margin: 5px 0; }
.src { font-size: 12px; color: #8a97a5; margin-top: 10px; }
.srcline { font-size: 12.5px; color: #66727f; margin-top: 10px; }
code { background: #f2f5f9; border-radius: 4px; padding: 1px 5px; font-size: 12.5px; }
.hint { background: #f8fafc; border: 1px dashed #d7dee7; border-radius: 10px; padding: 14px 16px;
        font-size: 13.5px; color: #5b6b7c; margin: 10px 0; }
.tbl-wrap { overflow-x: auto; }
table.data { width: 100%; border-collapse: collapse; font-size: 13.5px; margin-top: 8px; }
table.data th, table.data td { border: 1px solid #e3e8ef; padding: 8px 10px; text-align: left; vertical-align: top; }
table.data thead th { background: #f5f7fa; font-weight: 600; font-size: 13px; }
table.data .num { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
table.data .note { color: #6b7886; }
table.data tr.sum td { background: #fafbfc; }
table.data tr.total td { background: #eef3ff; font-weight: 700; }
table.data td.cat { font-weight: 600; white-space: nowrap; }
.nowrap { white-space: nowrap; }
.muted { color: #9aa5b1; font-size: 12.5px; }
.climate { font-size: 14px; background: #f8fafc; border-left: 3px solid #9ec5fe;
           padding: 10px 14px; border-radius: 0 8px 8px 0; margin: 0 0 6px; }
/* 逐日行程 */
.day { border: 1px solid #e6ebf1; border-radius: 12px; padding: 14px 16px; margin-bottom: 12px; }
.dayhead { display: flex; align-items: baseline; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }
.dnum { background: #4361ee; color: #fff; border-radius: 7px; padding: 2px 9px; font-size: 12.5px; font-weight: 700; }
.dtheme { font-size: 15.5px; font-weight: 700; }
.ddate { font-size: 12.5px; color: #8a97a5; }
ul.timeline { list-style: none; margin: 0; padding: 0; }
li.stop { display: flex; gap: 12px; padding: 8px 0; border-top: 1px dashed #eef1f5; }
li.stop:first-child { border-top: none; }
li.stop .t { flex: 0 0 52px; font-size: 12.5px; color: #4361ee; font-variant-numeric: tabular-nums; padding-top: 1px; }
li.stop .body { flex: 1; }
li.stop .n { font-size: 14.5px; font-weight: 600; }
li.stop .note { font-size: 13px; color: #5b6b7c; }
ul.facts { margin: 5px 0 0; padding-left: 16px; font-size: 12.5px; color: #3e4c59; }
ul.facts .fk { color: #8a97a5; }
ul.facts .fsrc { color: #a0aab5; }
.alt { margin-top: 5px; font-size: 12.5px; color: #7a5b1e; background: #fdf6e6;
       border-radius: 6px; padding: 4px 8px; display: inline-block; }
.tag { background: #e8b04b; color: #fff; border-radius: 4px; padding: 0 5px; margin-right: 6px; font-size: 11px; }
/* 清单 */
.sub2 { font-size: 14px; font-weight: 700; margin: 18px 0 8px; }
.tl .bucket { padding: 7px 0; border-top: 1px dashed #eef1f5; }
.tl .bucket:first-child { border-top: none; }
.tl .lead { font-weight: 700; font-size: 13.5px; color: #4361ee; margin-bottom: 4px; }
.tl ul, .card ul { list-style: none; margin: 0; padding: 0; }
.ck { display: flex; align-items: flex-start; gap: 8px; font-size: 13.5px; padding: 3px 0; cursor: pointer; }
.ck input { margin-top: 4px; width: 15px; height: 15px; accent-color: #4361ee; flex: 0 0 auto; }
.ck input:checked + span { color: #9aa6b2; text-decoration: line-through; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 12px; }
.card { border: 1px solid #e6ebf1; border-radius: 10px; padding: 12px 14px; background: #fcfdff; }
.ctitle { font-weight: 700; font-size: 13.5px; }
.csum { font-size: 12px; color: #6b7886; margin: 2px 0 6px; }
ul.notes { margin-top: 14px; }
ul.notes li { font-size: 13.5px; }
figure { margin: 0 0 12px; }
figure img { width: 100%; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,.1); display: block; }
figcaption { font-size: 12.5px; color: #8a97a5; text-align: center; margin-top: 8px; }
footer { margin-top: 36px; padding-top: 16px; border-top: 1px solid #eef1f5;
         font-size: 12px; color: #8a97a5; line-height: 1.8; }
.bar { position: fixed; right: 20px; bottom: 20px; z-index: 9; display: flex; gap: 8px; }
.bar button { border: none; background: #4361ee; color: #fff; padding: 10px 18px; border-radius: 22px;
              font-size: 13px; cursor: pointer; box-shadow: 0 4px 14px rgba(67,97,238,.32); }
body.theme-watercolor .page { background: #fffdf6; }
body.theme-vintage .page { background: #fdf8ec; }
body.theme-sticker .page { background: #fdfdfb; }
@media (max-width: 680px) {
  body { padding: 12px 8px 40px; }
  .page { padding: 22px 18px 24px; border-radius: 12px; }
  .cover h1 { font-size: 21px; }
  .grid { grid-template-columns: 1fr; }
  .facts { grid-template-columns: 1fr 1fr; gap: 8px; }
  .fact { padding: 8px 10px; }
  .bar { display: none; }
}
@media print {
  body { background: #fff; padding: 0; }
  .page { box-shadow: none; max-width: none; padding: 0; }
  .bar, .style-switch { display: none !important; }
  .page { background: #fff !important; }
  section, .day, .block, .card, figure, table { break-inside: avoid; }
  h2 { break-after: avoid; }
  a { color: inherit; text-decoration: none; }
}
"""


def build_html(itin, asset_dirs, embed, weather=None, checklist=None):
    trip = itin.get("trip", {})
    sd, ed = trip_dates(itin)
    bv = budget_view(trip.get("budget"), trip.get("travelers"))
    body = (
        render_header(trip, sd, ed)
        + render_research(trip.get("research"))
        + render_weather(weather, trip)
        + render_days(itin)
        + render_route(itin, asset_dirs, embed)
        + render_budget(bv, trip)
        + render_checklist(checklist)
        + render_footer(trip, weather)
    )
    title = (trip.get("title") or "旅行方案") + " · 方案书"
    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{esc(title)}</title>
<style>{PAGE_CSS}{THEME_CSS}</style>
</head>
<body>
<div class="page">
  <div class="bar"><button onclick="window.print()">打印 / 导出 PDF</button></div>
  {THEME_BAR}
  {body}
</div>
<script>
  document.querySelectorAll('.ck input').forEach(function(cb, idx){{
    var k = 'plan_ck_' + idx;
    try {{ cb.checked = localStorage.getItem(k) === '1'; }} catch(e) {{}}
    cb.addEventListener('change', function(){{ try {{ localStorage.setItem(k, cb.checked ? '1' : '0'); }} catch(e) {{}} }});
  }});
</script>
{THEME_JS}
</body>
</html>
"""


# ---------------------------------------------------------------- 自检 & PDF

def find_chrome():
    cands = [
        os.environ.get("CHROME_PATH"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("chrome"),
    ]
    for c in cands:
        if c and Path(c).exists():
            return c
    return None


def export_pdf(html_path, pdf_path):
    chrome = find_chrome()
    if not chrome:
        return False, "未找到 Chrome/Edge，跳过 PDF（可用浏览器「打印 → 存储为 PDF」）"
    try:
        subprocess.run(
            [chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
             "--no-pdf-header-footer", f"--print-to-pdf={pdf_path}", html_path.resolve().as_uri()],
            check=True, capture_output=True, timeout=120,
        )
    except subprocess.CalledProcessError as e:
        return False, f"PDF 导出失败：{e.stderr.decode('utf-8', 'ignore')[:200]}"
    except Exception as e:  # noqa: BLE001
        return False, f"PDF 导出失败：{e}"
    return pdf_path.exists(), ""


def verify(html, itin, weather, checklist):
    report = []
    # 占位符残留检测：模板里不应再出现双下划线包裹的大写标记
    import re
    leftovers = set(re.findall(r"__[A-Z_]{3,}__", html))
    if leftovers:
        FATAL.append("HTML 存在未替换占位符：" + "、".join(sorted(leftovers)))
    stops = [s for s in (itin.get("stops") or []) if s and s.get("name")]
    rendered = html.count('class="stop"')
    if rendered != len(stops):
        FATAL.append(f"站点渲染数（{rendered}）与 JSON（{len(stops)}）不一致")
    if weather and not any(c.get("available") for c in (weather.get("cards") or [])):
        MISSING.append("气象数据全部超出预报窗口/不可达（页面显示「临近再查」）")
    for m in dict.fromkeys(MISSING):
        report.append("⚠️ " + m)
    for m in dict.fromkeys(FATAL):
        report.append("❌ " + m)
    if not report:
        report.append("✅ 结构完整：七节齐全，站点/预算/图片均通过校验")
    return (not FATAL), report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("itinerary", help="itinerary.json 路径")
    ap.add_argument("--out", default=None, help="输出目录（默认与 json 同目录）")
    ap.add_argument("--checklist", default=None, help="checklist.json 路径（默认找输出目录里的）")
    ap.add_argument("--weather", default=None, help="weather.json 路径（默认找输出目录里的）")
    ap.add_argument("--no-embed", action="store_true", help="图片改用相对路径引用（不生成单文件）")
    ap.add_argument("--pdf", action="store_true", help="用系统 Chrome 导出 plan.pdf")
    ap.add_argument("--skip-verify", action="store_true", help="跳过自检（不推荐）")
    args = ap.parse_args()

    itin_path = Path(args.itinerary).resolve()
    itin = json.loads(itin_path.read_text(encoding="utf-8"))
    out = Path(args.out).resolve() if args.out else itin_path.parent
    out.mkdir(parents=True, exist_ok=True)

    weather_path = Path(args.weather).resolve() if args.weather else out / "weather.json"
    checklist_path = Path(args.checklist).resolve() if args.checklist else out / "checklist.json"
    # 产物目录和行程目录可能不同：图片/清单/气象在两边都找一遍
    asset_dirs = [out] if itin_path.parent == out else [out, itin_path.parent]
    if not args.weather and not weather_path.exists() and (itin_path.parent / "weather.json").exists():
        weather_path = itin_path.parent / "weather.json"
    if not args.checklist and not checklist_path.exists() and (itin_path.parent / "checklist.json").exists():
        checklist_path = itin_path.parent / "checklist.json"
    weather = load_json(weather_path)
    checklist = load_json(checklist_path)

    html = build_html(itin, asset_dirs, embed=not args.no_embed, weather=weather, checklist=checklist)
    out_path = out / "plan.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"✅ plan.html: {out_path}（{len(html.encode('utf-8'))/1024:.0f} KB）")

    ok = True
    if not args.skip_verify:
        print("\n--- 方案书自检 ---")
        ok, report = verify(html, itin, weather, checklist)
        for line in report:
            print("  " + line)
        if not ok:
            print("\n❌ 自检未通过：请勿交付，先修上方 ❌ 项。")

    if args.pdf:
        pdf_ok, msg = export_pdf(out_path, out / "plan.pdf")
        if pdf_ok:
            print(f"✅ plan.pdf: {out / 'plan.pdf'}")
        else:
            print(f"⚠️ {msg}")

    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
