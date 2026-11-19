# 专家中心素材（v1.3）

上线用文案与样张。图片在 `docs/gallery/`，全部来自真实产出（西双版纳 · 普洱 7 日亲子环线），可直接上传到专家详情页。

## 一句话卖点

> 问一句就答，认真排就给一整套——方案书、地图、海报，能看的能发的都有。

备选：
- 「门票、交通、天气，查完就答并带来源；真排行程，就给你一份能转发的方案书。」
- 「从前台咨询到整套方案：可打印的方案书 + 可缩放地图 + 手绘分享图。」
- 「4 轮对话，换一趟排得动的旅行，和一组发得出去的图。」

## 详情页描述（可直接粘贴）

**中文**
> 两种用法。**当顾问**：门票多少钱、怎么坐车、明天什么天气、要不要预约——实时检索后直接给答案，带来源和月份，不用等一份方案。**当方案专家**：和「小游」像朋友一样聊清楚这趟旅行——去哪、几天、谁一起、想怎么玩。她会先核对动线和单日车程，避免「一天塞六个景点」和「首晚住到反向端点」，再给你按天草稿，改到满意才出图。
>
> 确认后一次交付：一份**单文件方案书**（目的地调研 / 天气研判 / 逐日行程含备选 / 路线图与动线 / 预算明细 / 出行清单，七节齐全，手机可读、可转发、可打印成 PDF）、可缩放的交互地图、适合转发的路线长图、按目的地和季节定制的出行前清单、以及出发前可再查一次的实时天气。
>
> 所有价格、开放时间、预约政策都来自实时检索并标注来源月份，方案书页脚固定写明「信息基准日」——出发前照着复核一遍就行。
>
> 还会配一套**不带底图的手绘分享图**：每日海报、封面、景点速览、金句卡，手机尺寸直出，发群或朋友圈都清晰。插画按「每天头牌景点」生成，用多少积分你说了算。
>
> 想要地图版也可以：整趟一张「方形地图 + 每日摘要」的海报，或每天一张「当日路线 + 站点时间」的地图卡——本机渲染、不消耗生图积分，要不要由你决定。

**English**
> Two modes. As an advisor: tickets, transit, weather, booking rules — sourced answers in seconds. As a planner: it checks feasibility first — route order, first-night gateway, and realistic daily driving time — then drafts day by day until you approve.
>
> You get a single-file plan document (research, weather with per-day impact, day-by-day plan with rain alternatives, route + daily flow, budget breakdown, checklist) that is readable on a phone, forwardable on WeChat and printable to PDF — plus a zoomable interactive map, a route image, a tailored pre-trip checklist and refreshable live weather.
>
> Plus a set of map-free, phone-sized hand-drawn posters (daily, cover, highlights, quote cards) that are ready to share.

## 样张上传顺序

| 顺序 | 文件 | 说明（建议作为图注） |
|---|---|---|
| 1 | `01-cover.jpg` | 手绘封面：行程标题 + 日期 + 同行人 |
| 2 | `02-route-map.jpg` | 左文右图路线长图，按天配色、景点名常驻 |
| 3 | `03-day-poster.jpg` | 每日海报：DAY 徽章 + 插画 + 当日站点 |
| 4 | `04-grid.jpg` | 景点速览九宫格，适合做行程概览 |
| 5 | `05-checklist.jpg` | 出行前清单：按「距出发还有几天」压缩的时间线 |
| 6 | `06-weather.jpg` | 逐日天气卡：标注数据取站与温度区间 |
| 7 | `07-map-poster.jpg` | 整趟地图海报：方形地图 + 每日一行摘要，手机全屏可直接发 |
| 8 | `08-map-day.jpg` | 每日地图卡：当天路线 + 站点时间，只显示当天站点与路段 |
| 9 | `09-plan-doc.jpg` | 方案书 plan.html：摘要 + 逐日行程 + 预算明细，单文件可转发可打印 |

## 快速开始（quickPrompts 已内置）

1. 「我想规划一次旅行，请一步步帮我确认细节……」
2. 「帮我在成都规划 5 天，主打美食和慢生活的行程」← **首轮即出草稿**
3. 「故宫门票多少钱？需要提前预约吗」← **L1 顾问快答，不出文件**
4. 「把这份行程做成可以发朋友圈的手绘海报」
5. 「出发前帮我查一下实时天气，并更新出行清单」

## 常见疑问（可放详情页底部）

- **要不要先回答一堆问题？** 不用。说了目的地和天数，就直接给草稿，最多再问 3 个待定项。只问单一事实时，它只回答、不推销整套方案。
- **价格是实时的吗？** 是检索来的，每条都标来源与月份，页脚有「信息基准日」；出发前照着复核即可。
- **方案书里有什么？** 七节：摘要 / 目的地调研 / 天气研判 / 逐日行程（含雨天备选）/ 路线图与动线 / 预算明细（六分项 + 弹性 + 人均）/ 出行清单。
- **插画会花我的积分吗？** 会，约 5–10 积分/张，只画每天头牌，生成前会先问你。
- **没有网络/查不到小景点怎么办？** 冷门景点手填一次坐标后会进缓存；底图加载失败会自动回退，文字行程照常交付。
- **出发前天气变了？** 带同一份行程文件再打开一次，说「查天气」即可拉最新预报并更新清单。
