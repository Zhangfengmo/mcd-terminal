---
name: mcd-terminal
description: 麦当劳省钱点餐助手。帮用户点麦当劳、查积分和优惠券、把快过期的积分换掉；点餐时自动叠加已有优惠券、积分和门店活动，实时核价算出实付最低的付法，并提醒顺手能用掉的券和积分。当用户提到麦当劳、点餐、巨无霸/麦乐鸡等餐品、麦当劳积分或优惠券时使用。
---

# 麦麦交易终端：麦当劳省钱点餐 Skill

这个 Skill 让你能可靠地帮用户点麦当劳，并且总是用最省的方式付款。它基于麦当劳中国官方 MCP，由命令行引擎 `mcd` 完成需要精确计算的部分：

- **最优付法**：每样东西在“现金 / 已有优惠券 / 先用积分兑换”三种方式里选，整单实付最低。这是一个组合优化问题，交给 `mcd` 算，不要自己心算。
- **实时核价**：门店活动、配送费、团餐折扣以麦当劳服务端的报价为准。
- **加购建议**：快过期的闲置券、用剩积分能兑换的商品、第二份半价，问用户要不要顺便带上。
- **安全**：扣积分和下单都必须先得到用户同意，付款由用户自己完成。

## 第一次使用

1. 运行 `mcd --version` 检查引擎是否已安装。如果没有装，告诉用户需要安装，**得到同意后**再运行：

   ```bash
   curl -fsSL --max-time 60 https://gh-proxy.com/https://github.com/Zhangfengmo/mcd-terminal/releases/latest/download/install.sh | bash
   # 海外网络去掉 https://gh-proxy.com/ 前缀；Windows：irm <同样的地址，install.ps1> | iex
   ```

   安装脚本会强制校验 SHA-256，装到 `~/.local/bin/mcd`（Windows 是 `%LOCALAPPDATA%\mcd-terminal`）。如果当前会话找不到命令，就用完整路径调用。

2. 运行 `mcd --json doctor`。如果提示需要登录，请用户自己在终端运行 `mcd login` 粘贴 Token（在 https://open.mcd.cn/mcp 申请）。只有用户主动把 Token 交给你时，才用 `mcd --json login --token <Token>`，并且不要在回复里复述 Token。

3. 用户还没有 Token、只想先看看效果时，所有命令都可以加 `--demo` 使用演示数据。

## 三条规则

1. **永远加 `--json`**：`mcd --json <命令>`，stdout 只有一个 JSON 对象。先看 `ok`；为 `false` 时把 `error` 用自己的话告诉用户。
2. **不经用户同意，绝不加 `--yes`**。`order`、`spend`、`buy`、`claim`、`cancel`、`draw`、`party --book` 会扣积分、领券、抽奖、创建或取消订单、预约派对。不加 `--yes` 时只返回方案，并标记 `"status": "needs_confirmation"`。你要把方案讲给用户听（买什么、每样怎么付、用多少积分、实付多少），用户明确同意后，再执行返回值里的 `confirm_with` 命令（即原命令加 `--yes`）。积分扣除不可撤销。
3. **你不能替用户付款**。下单成功后返回 `order.scan_url`（手机扫码或点开就进麦当劳 App 收银台，优先给这个）、`order.app_url`（手机上直接拉起 App）和 `order.pay_url`（电脑上看的扫码页）。把链接交给用户自己付款。

## 常见任务

| 用户说 | 你执行 |
| --- | --- |
| “今天有什么要注意的”“我的麦当劳” | `mcd --json` |
| “帮我点个巨无霸和拿铁” | `mcd --json order 巨无霸 中杯拿铁` → 讲方案 → 用户同意 → `confirm_with` |
| “点两份薯条，送到家” | `mcd --json order 薯条x2 --delivery` |
| “在人民广场附近取餐” | `mcd --json order 巨无霸 --city 上海 --near 人民广场` |
| “明天中午 12 点给团队订 10 个汉堡” | `mcd --json order 巨无霸x10 --group --at "YYYY-MM-DD 12:00"` |
| “这单别用积分” / “最多用 1000 积分” | 加 `--no-points` / `--points 1000` |
| “有什么吃的”“薯条多少钱” | `mcd --json menu [关键词]` |
| “想吃低卡的”“哪个蛋白质高” | `mcd --json nutrition [--sort protein]`，再结合 `menu` 推荐 |
| “我有多少积分/券” | `mcd --json portfolio` |
| “积分快过期了怎么办” | `mcd --json spend --expiring` → 讲方案 → 同意后 `confirm_with` |
| “积分换什么最划算” | `mcd --json market` |
| “帮我领券” | `mcd --json claim` → 同意后 `confirm_with` |
| “我的餐好了吗” | `mcd --json track`（默认最近一单）或 `track <订单号>` |
| “我最近点了什么” | `mcd --json orders` |
| “我这周吃了多少热量”“这个月在麦当劳摄入了多少” | `mcd --json stats`：`periods.today/week/month/all` 里有热量、蛋白质、脂肪、碳水、钠、花费和日均；`not_counted` 是查不到营养数据的餐品。只陈述数字和参考量，不评判、不给节食建议 |
| “刚才那单不要了” | `mcd --json cancel [订单号]` → 确认是哪一单 → 同意后 `confirm_with` |
| “我的默认门店/地址是什么” | `mcd --json config` |
| “以后都送到家” / “默认去人民广场那家” | `mcd --json config mode delivery` / `mcd --json config store --city 上海 --near 人民广场` |
| “积分抽奖有什么奖品”“我抽中了什么” | `mcd --json prizes` |
| “帮我抽一次奖” | `mcd --json draw` → 把 `cost`（本次扣多少次数/积分，`lottery.then` 不为空时说明次数用完后改扣积分）告诉用户 → 用户明确说“抽”后执行 `confirm_with`；一次只抽一次，不要试抽、连抽；“试试看”“能抽就抽”不算确认 |
| “有什么派对/亲子活动”“生日派对哪天能约” | `mcd --json events`，再 `mcd --json party <名字> --city <城市>` |
| “孩子生日想办个派对，我们大概 4 个人” | `mcd --json party <名字> --city <城市> --people 4 --by <生日>`：看 `recommended`（按“最不怕凑不齐”排好，`safe` 为 true 表示不用等别人，`need_more` 是还差几人、`deadline`/`hours_left` 是拉人截止）。拼团截止前凑不够最少人数会**自动取消并退款**，需提前 3 天预订——一定把这两条和风险讲给用户 |
| “帮我约周六上午的生日派对” | `mcd --json party <名字> --city <城市> --book`：`status` 为 `choose_session` 时让用户选场次再加 `--date --time`；`choose_type` 时问包场还是拼团再加 `--type`；人数用 `--count`；`needs_confirmation` 时讲清楚门店、时间、方式、人数、价格，同意后 `confirm_with`，把 `order.scan_url`（没有就用 `pay_url`）给用户付款；拼团还差人时把 `invite_text` 给用户转发拉人，并建议用 `reminders` 里的命令设截止前提醒 |
| “问卷送的券呢”“上次填的问卷有券吗” | `mcd --json survey [订单号]` |
| “给公司订团餐，看看怎么凑满减” | `mcd --json order <餐品> --group`，看 `group_promotions`：`applied` 是已享受的一档，`next.add_yuan` 是再加多少到下一档、`next.fill_with` 是刚好够的一样 |
| “券快过期了提醒我”“这个活动开始时提醒我” | `mcd --json remind coupons` / `remind campaign -t <活动名>` → 讲清楚加什么提醒 → 同意后 `confirm_with` |
| “给我一个网页看看” | 让用户自己运行 `mcd web`（打开浏览器的图形界面，agent 不需要调用它） |
| “最近有什么活动” | `mcd --json calendar` |
| “加个收货地址” | `mcd --json address add --city --name --phone --street --detail` |

餐品名可以说得很随意：“薯条”会匹配到“中薯条”。数量写成 `名字x数量`（如 `麦乐鸡x2`；不要用 `*`，zsh 会把它当通配符报错）。门店和地址用过一次就会记住，之后不用重复传；第一次没传位置时，会依次用收藏门店、上次点餐的门店、收货地址附近的门店。

用户保存过的默认设置（`mcd config`：点餐方式、门店、收货地址、积分用法、堂食/外带）会自动生效，不用每次都传 `--delivery`、`--near` 这些参数；命令里的参数优先于默认设置。只有用户明确说“以后都…”时才去改默认设置。加地址前不用自己查重，`address add` 遇到相同地址会直接复用。

店里没有某样东西时返回 `"status": "not_on_menu"`，带 `alternatives`（相近的餐品）和 `retry_with`（换成第一个相近餐品的命令）。先问用户要不要换，不要直接替用户换。

## 关键返回字段

**order**（最重要）

```json
{
  "ok": true, "command": "order", "status": "needs_confirmation",
  "scene": {"mode": "pickup", "label": "到店自取", "store": "麦当劳人民广场餐厅"},
  "plan": {
    "original_yuan": 68.5, "pay_yuan": 21.8, "saving_yuan": 46.7, "points_used": 1700, "coupons_used": 2,
    "lines": [
      {"item": "巨无霸", "price_yuan": 25.0, "pay_with": "points", "points": 1200, "pay_yuan": 0.0},
      {"item": "中份薯条", "price_yuan": 12.0, "pay_with": "coupon", "coupon": "9.9元薯你最甜", "pay_yuan": 9.9},
      {"item": "麦乐鸡 5 块", "price_yuan": 14.5, "pay_with": "cash", "pay_yuan": 14.5}
    ]
  },
  "kcal": 1200,
  "quote": {"pay_yuan": 21.8, "delivery_yuan": 0.0, "promo_saving_yuan": 0.0},
  "campaigns_today": [{"title": "…", "items": ["麦辣鸡腿堡"], "in_cart": false}],
  "suggestions": [
    {"kind": "points", "add": "圆筒冰淇淋", "points": 150, "pay_yuan": 0.0,
     "message": "剩下的 180 积分还能免费带一个圆筒冰淇淋（150 积分，价值 ¥5.00）",
     "command": "mcd --json order 巨无霸 中杯拿铁 薯条 麦乐鸡 圆筒冰淇淋"}
  ],
  "confirm_with": "mcd --json order 巨无霸 中杯拿铁 薯条 麦乐鸡 --yes"
}
```

- **以 `quote.pay_yuan` 为准**：这是服务端对现金和券部分的实时报价，已经算进门店活动、配送费和团餐折扣；`plan.pay_yuan` 只是本地估算。
- **`suggestions` 是加购建议**：区分“用户想买的”和“顺便更划算的”，包括快过期的闲置券（`kind: coupon`，看 `days_left`）、用剩积分能兑的商品（`points`）、第二份半价（`promo`）。把 `message` 转述给用户问要不要加；用户要的话执行 `command`（会得到新方案），不要的话照原方案走。不要替用户决定加不加。
- **`campaigns_today`**：今天和本店菜单相关的活动，可以顺带告诉用户。

`pay_with` 的取值：`cash` 付现金，`coupon` 用已有的券，`points` 先用积分兑换再使用。执行成功后 `status` 变为 `ordered`，并带上 `order.order_id`、`order.scan_url`、`order.app_url`、`order.pay_url` 和 `order.pay_yuan`。

**status 的取值**：`planned` 只是方案（`--dry-run`）· `needs_confirmation` 等待用户同意 · `ordered`/`done` 已执行 · `cancelled` 用户取消 · `nothing_to_do` 无事可做。

其他命令：`today` → `points`、`expiring_coupons`、`claimable`、`campaigns_today`、`suggestion`；`portfolio` → `points`、`coupons`；`spend` → `plan.picks`；`menu` → `items[].{name,price_yuan,kcal,code}`；`track` → `order.{status,hint,pickup_code}`；`orders` → `orders[].{order_id,items,pay_yuan,status}`；`cancel` → `cancelled`。

积分商城里的餐品大多是折扣券（如“6.9元可乐麦炫酷”）：积分换到券后，到店还要按券价付钱，`market` 返回的 `use_price_yuan` 就是这个价，`value_yuan` 是真正省下的钱。讲方案时要说清楚这一点。

## 和用户说话的方式

- 先说结论：“这单原价 ¥68.5，用 2 张券和 1700 积分，实付 ¥21.8。”再列出每样怎么付。
- 方案用了积分时，提醒“积分兑换后不能撤销”。
- 热量（`kcal`）只做参考，不评价用户吃什么。
- 外送的配送费和团餐的满额折扣以下单时为准（看 `notes`）。

## 出错时

| `error` 里包含 | 怎么办 |
| --- | --- |
| `mcd login` / `401` | 请用户在 https://open.mcd.cn/mcp 获取 Token，然后执行 `mcd login` |
| `429` | 稍等一分钟再试，不要连续重试 |
| `没找到「…」` | 用 `menu` 查到准确的餐品名后重试 |
| `还没有收藏的门店` | 问用户在哪，加 `--city --near` |
| `还没有收货地址` | 问用户地址后执行 `address add` |
| `积分不足` | 用 `--points` 降低预算，或改用 `--no-points` |

退出码：成功为 0，失败为 1，参数错误为 2。
