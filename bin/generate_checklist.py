#!/usr/bin/env python3
"""读取 checklist.json，渲染可勾选、可打印的出行前 Checklist（checklist.html）。

用法:
    python3 generate_checklist.py <checklist.json> [--out <目录>]

- 纯静态 HTML，无需浏览器/playwright，双击即可打开、勾选、打印成 PDF。
- 内容由「旅行规划师」专家结合目的地地理 + 日期/季节 + 已确认站点推理生成（结构见 references/checklist-guide.md）。
"""
import argparse
import html
import json
from pathlib import Path


def esc(t):
    return html.escape("" if t is None else str(t), quote=True)


def meta_line(meta):
    parts = [
        meta.get("destination"),
        (meta.get("start_date") or "") and f"出发 {meta['start_date']}",
        meta.get("days") and f"{meta['days']}天",
        meta.get("season"),
        meta.get("travelers"),
        meta.get("transport"),
    ]
    return " · ".join(esc(p) for p in parts if p)


def render_timeline(timeline):
    if not timeline:
        return ""
    rows = []
    for bucket in timeline:
        lead = esc(bucket.get("lead", ""))
        items = "".join(
            f'<li><label class="ck"><input type="checkbox"/><span>{esc(i)}</span></label></li>'
            for i in bucket.get("items", [])
        )
        rows.append(
            f'<div class="bucket"><div class="lead">{lead}</div><ul class="items">{items}</ul></div>'
        )
    return f'<section><h2>⏰ 提前预约时间线</h2>{"".join(rows)}</section>'


def render_categories(categories):
    if not categories:
        return ""
    cards = []
    for key, c in categories.items():
        if not c:
            continue
        title = esc(c.get("title", key))
        summary = esc(c.get("summary", ""))
        items = "".join(
            f'<li><label class="ck"><input type="checkbox"/><span>{esc(i)}</span></label></li>'
            for i in c.get("items", [])
        )
        cards.append(
            f'<div class="card"><div class="ctitle">{title}</div>'
            f'<div class="csum">{summary}</div><ul class="items">{items}</ul></div>'
        )
    return f'<section><h2>✅ 分类检查项</h2><div class="grid">{"".join(cards)}</div></section>'


def render_notes(notes):
    if not notes:
        return ""
    items = "".join(f"<li>{esc(n)}</li>" for n in notes)
    return f'<section><h2>📌 结合本行程的特别提醒</h2><ul class="notes">{items}</ul></section>'


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>__TITLE__ · 出行前 Checklist</title>
<style>
  * { box-sizing: border-box; }
  body { margin: 0; padding: 28px 22px 60px; max-width: 960px; margin: 0 auto;
         font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; color: #1f2933; background: #f7f9fc; }
  header { background: #fff; border-radius: 12px; padding: 18px 20px; box-shadow: 0 1px 3px rgba(0,0,0,.06); margin-bottom: 18px; }
  header h1 { font-size: 22px; margin: 0 0 6px; }
  header .meta { font-size: 13px; color: #5b6b7c; line-height: 1.7; }
  h2 { font-size: 17px; margin: 22px 0 12px; padding-left: 10px; border-left: 4px solid #4361ee; }
  section { background: #fff; border-radius: 12px; padding: 16px 18px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,.05); }
  .bucket { padding: 8px 0; border-top: 1px dashed #eef1f5; }
  .bucket:first-of-type { border-top: none; }
  .lead { font-weight: 700; color: #4361ee; font-size: 14px; margin-bottom: 6px; }
  .items { list-style: none; margin: 0; padding: 0; }
  .items li { padding: 5px 0; }
  .ck { display: flex; align-items: flex-start; gap: 9px; cursor: pointer; font-size: 14px; line-height: 1.5; }
  .ck input { margin-top: 3px; width: 16px; height: 16px; accent-color: #4361ee; flex: 0 0 auto; }
  .ck input:checked + span { color: #9aa6b2; text-decoration: line-through; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .card { border: 1px solid #e4e9f0; border-radius: 10px; padding: 12px 14px; background: #fcfdff; }
  .ctitle { font-weight: 700; font-size: 14px; margin-bottom: 4px; }
  .csum { font-size: 12px; color: #6b7886; margin-bottom: 8px; line-height: 1.6; }
  .notes li { padding: 5px 0; font-size: 14px; color: #334; }
  .bar { position: sticky; top: 0; display: flex; gap: 10px; justify-content: flex-end; padding: 8px 0; }
  .bar button { border: none; background: #4361ee; color: #fff; padding: 8px 16px; border-radius: 8px; font-size: 13px; cursor: pointer; }
  @media print {
    body { background: #fff; }
    section, header { box-shadow: none; }
    .bar { display: none; }
  }
  @media (max-width: 640px) { .grid { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<div class="bar"><button onclick="window.print()">打印 / 导出 PDF</button></div>
__BODY__
<script>
  // 勾选状态本地记忆，刷新不丢失
  document.querySelectorAll('.ck input').forEach(function(cb, idx){
    var k = 'ck_' + idx;
    cb.checked = localStorage.getItem(k) === '1';
    cb.addEventListener('change', function(){ localStorage.setItem(k, cb.checked ? '1' : '0'); });
  });
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("checklist", help="checklist.json 路径")
    ap.add_argument("--out", default=None, help="输出目录（默认与 json 同目录）")
    args = ap.parse_args()

    path = Path(args.checklist).resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    meta = data.get("meta", {})
    title = esc(meta.get("destination") or "旅行") + " 出行前 Checklist"

    body = (
        f'<header><h1>{title}</h1><div class="meta">{meta_line(meta)}</div></header>'
        + render_timeline(data.get("timeline", []))
        + render_categories(data.get("categories", {}))
        + render_notes(data.get("notes", []))
    )
    out = Path(args.out).resolve() if args.out else path.parent
    out.mkdir(parents=True, exist_ok=True)
    out_path = out / "checklist.html"
    out_path.write_text(
        HTML_TEMPLATE.replace("__BODY__", body).replace("__TITLE__", title),
        encoding="utf-8",
    )
    print(f"✅ Checklist: {out_path}")


if __name__ == "__main__":
    main()
