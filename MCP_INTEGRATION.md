# MCP 集成说明

## 使用的 MCP Server

| 项目 | 值 |
| --- | --- |
| Server | 麦当劳中国 MCP Server（`mcd-mcp`） |
| 地址 | `https://mcp.mcd.cn` |
| 传输协议 | Streamable HTTP |
| 协议版本 | `2025-06-18`（服务端支持的最高版本） |
| 鉴权 | `Authorization: Bearer <MCP Token>`。Token 来自 `mcd login`（保存在本机、仅本人可读）或环境变量 `MCD_MCP_TOKEN`（优先） |

客户端（`mcd_terminal/client.py`）直接实现 JSON-RPC over HTTP：先 `initialize` 握手，记录 `Mcp-Session-Id`，再发送 `notifications/initialized`；之后每次 `tools/call` 都带上会话 ID 和协议版本头。JSON 和 SSE 两种响应都能处理，退出时用 `DELETE` 结束会话。401（Token 无效）和 429（超过每分钟 600 次）会转成中文提示。

## 用到的 Tool（35 个，全部接入）

服务端目前提供 35 个工具，本项目全部接入：积分、优惠券、点餐、订单、团餐满减、问卷奖券、积分抽奖，以及派对和体验活动的预约。会扣积分、抽奖、下单或预约的操作（`mall-create-order`、`create-order`、`draw-lottery`、`party-order-create`、`cancel-order`、`auto-bind-coupons`）都要先把要做的事讲清楚，用户确认后才调用；agent 模式下不加 `--yes` 只返回方案。

| 能力 | Tool | 用在哪 |
| --- | --- | --- |
| 通用 | `now-time-info` | 今日简报：按时段问候、计算券的剩余天数 |
| 积分 | `query-my-account` | 简报、持仓、清仓预算、点餐时的积分预算 |
| 优惠券 | `query-my-coupons` | 简报中的到期提醒、持仓 |
| 麦麦省 | `available-coupons` / `auto-bind-coupons` | 简报中的可领提醒、`mcd claim` 一键领券 |
| 活动 | `campaign-calendar` | 简报中的今日活动、点餐时提示与这单相关的活动、`mcd calendar` |
| 积分商城 | `mall-points-products` / `mall-product-detail` | 行情估值（分/积分）、清仓规划、点餐时找“积分同款” |
| 积分兑换 | `mall-create-order` | 清仓兑换、点餐时先兑后用；`spuCategory=2` 加收货地址即为实物周边（`mcd buy <skuId> --address`） |
| 兑换记录 | `mall-order-list` / `mall-order-detail` | `mcd history` |
| 门店 | `query-nearby-stores` | 到店 / 得来速选店、`mcd stores` |
| 地址 | `delivery-query-addresses` / `delivery-create-address` | 外送和团餐选地址、`mcd address`、`mcd config address`；添加前先查一遍，相同地址不重复创建 |
| 外送门店 | `delivery-query-stores` | 麦乐送、企业团餐 |
| 团餐 | `query-meal-assistance` | 团餐助餐服务及满额折扣 |
| 团餐满减满折 | `query-promotions` | `mcd order --group`：这单能享受哪一档满减/满折、再加多少钱到下一档、加哪样刚好够（只算现金部分，以核价为准） |
| 菜单 | `query-meals` / `query-meal-detail` | 点餐时匹配菜品并读取活动标签（如“第二份半价”）、`mcd menu`、套餐组成 |
| 营养 | `list-nutrition-foods` | 点餐时估算整餐热量、菜单热量列、`mcd nutrition` |
| 门店可用券 | `query-store-coupons` | 点餐时找可叠加的已有券 |
| 算价 | `calculate-price` | 试算每张券的用券价；确认前实时核价（含配送费、门店活动、团餐折扣）；下单前的最终价格 |
| 下单 | `create-order` | 创建订单，返回支付链接 |
| 订单进度 | `query-order` | `mcd track`：状态、取餐码、配送信息 |
| 点餐记录 | `order-list` | `mcd orders`；`mcd track` / `mcd cancel` / `mcd survey` 不带订单号时找最近的订单 |
| 问卷奖券 | `query-survey-coupon` | `mcd survey`：吃完填的满意度问卷送了什么券、有效期、是否已核销、适用到店还是外送；网页版订单页的已完成订单下方 |
| 取消订单 | `cancel-order` | `mcd cancel`：确认后取消，可选取消原因 |
| 派对场次 | `query-party-city` / `query-party-store` / `query-party-store-date` / `query-party-store-session` | `mcd party`、网页版活动地图里的派对卡片：哪个城市、哪家店、哪天几点还能约 |
| 派对预约 | `party-order-create` | `mcd party <名字> --book`：按 城市 → 门店 → 日期 → 场次 → 包场/拼团 → 人数 一步步选（活动只支持一种时自动带上），确认后下单、扫码付款；网页版场次旁的“预约” |
| 积分抽奖 | `query-lottery-info` / `query-my-prizes` | `mcd prizes`、网页版活动页的奖池和“我的奖品” |
| 抽奖 | `draw-lottery` | `mcd draw`：先展示 `drawDecision.nextConsumption`（本次扣多少次数或积分，有 `fallbackConsumption` 时一并说明），`resourceEligible` 为 false 时不调用；用户确认后只抽一次，不试抽、不连抽；失败时原样展示服务端的提示。网页版奖池弹窗的“抽一次” |

`mcd doctor` 额外调用 MCP 标准方法 `tools/list`，逐一检查上面 35 个工具是否可用，并列出服务端新增的工具。

## 核心流程：券 + 积分 + 活动 + 实时核价，一单算到最省

`mcd order 巨无霸 中杯拿铁 薯条 麦乐鸡`

```
query-nearby-stores / delivery-query-addresses + delivery-query-stores   选门店（会记住）
[团餐] query-meal-assistance                                              选助餐服务
query-meals                                                              按名字匹配菜品，读取活动标签
query-store-coupons → calculate-price × N                                试算已有券的用券价
query-my-account + mall-points-products + mall-product-detail × N         本店能用积分兑换的商品
campaign-calendar                                                        今天和这单相关的活动
list-nutrition-foods                                                     估算整餐热量
        │
        ▼  ① 本地优化：每件商品在「现金 / 已有券 / 积分兑券」三选一
        │     已有券每张只能用一次：枚举券的分配，剩余商品做多选背包；
        │     目标是实付最低，金额相同时少用积分
        ▼  ② 实时核价：calculate-price 对现金和券的部分报价
        │     （门店活动、配送费、团餐折扣都以服务端为准）
        ▼  ③ 加购建议：区分“你想买的”和“顺便更划算的”
        │     · 这单没用上的券，尤其是快过期的
        │     · 用剩的积分正好够兑换的本店商品
        │     · 带“第二份半价”标签、只点了一份的商品
        │     用户选择加上后，重新优化并核价
        ▼  用户确认（确认框里显示核价后的金额）
mall-create-order × N        兑换计划中的积分券
query-store-coupons          找到刚到账的券
calculate-price              最终价格
create-order                 创建订单，返回支付链接（付款由用户完成）
```

其他命令的调用：

- `mcd`（今日简报）：`now-time-info`、`query-my-account`、`query-my-coupons`、`available-coupons`、`campaign-calendar`
- `mcd spend --expiring`：`query-my-account` → `mall-points-products` → `mall-product-detail` × N → 有界背包 → 确认后 `mall-create-order` × N
- `mcd track`：`query-order`
- `mcd orders`：`order-list`；`mcd cancel`：`order-list` → `query-order` → 确认后 `cancel-order`

## 真实服务端的几个细节

用真实账号测试后发现，线上返回和文档有些出入，引擎都已兼容（`tests/test_real_payloads.py` 用脱敏后的真实返回做了固定测试）：

- 大多数工具的 JSON（`{"success","code","message","data"}`）嵌在给大模型看的说明文字里，前后都可能有文字；优惠券、领券和活动日历直接返回 Markdown。
- 到店自取（`beType=1`）不能传 `beCode`；得来速、外送和团餐需要传。`create-order` 必须带 `orderType`。
- `query-nearby-stores` 只能查收藏门店或按“城市 + 关键词”搜索，不能按定位找最近的店；没有收藏时会直接报错。所以第一次点餐没给位置时，引擎依次用：上次点餐的门店（`order-list` 里带门店编码）→ 收货地址附近的门店 → 问用户一次在哪，之后都记住。
- 门店距离是以米为单位的整数；麦麦省可领的券状态是“可领取”。
- 积分商城里的餐品大多是**折扣券**（如“6.9元可乐麦炫酷”）：积分换到券，到店再按券价付钱。所以引擎计算积分价值时会减掉券价；组合、两件套、“任选”这类券不会自动对应到购物车里的单品；“到店专用”的券不会用在外送订单里；积分为 0 的条目是付费活动（派对、品鉴会），不参与积分计算。

## 网页版（mcd web）

`mcd web` 在本机起一个只监听 127.0.0.1 的小服务，页面通过一个接口运行和 `--json` 完全相同的命令，所以网页和 AI agent 用的是同一套接口、同一套确认规则：

- 每次启动生成一个随机密钥，只有 `mcd web` 打开的链接带着它；没有密钥、或 Host 不是本机的请求一律拒绝（防止别的网站借你的浏览器调用它）。
- 页面只能运行固定的几条命令，登录、退出、安装 Skill 只能在终端里做；Token 不会发给页面。
- 图片经本机服务转发，只允许麦当劳自己的图片域名（`*.mcd.cn` 和存放券图片的 `mcd-*.myqcloud.com`），所以门店菜单、积分商城、活动和奖品的图片在页面上都能显示，也不会被当成任意网址的代理。
- 付款二维码只会为麦当劳域名的支付链接生成。

## 和系统提醒联动（mcd remind）

券到期、积分到期、活动开始、派对场次可以放进用户自己的提醒应用。macOS 用 `osascript` 写进“提醒事项”的「麦麦提醒」列表（文字作为参数传入，不拼进脚本；同名未完成的提醒不会重复添加）；其他系统生成带闹钟的 `.ics` 日历文件，用默认日历应用打开。添加前同样需要用户确认（`--json` 下要加 `--yes`）。

## 安全设计

- 所有会扣积分、产生或取消订单的操作（`order`、`spend`、`buy`、`claim`、`cancel`）都会先弹出确认框；要跳过确认，必须显式加上 `--yes`。
- `create-order` 只生成待支付订单，付款始终由用户打开链接自己完成。
- Token 由 `mcd login` 验证有效后才保存到 `~/.config/mcd-terminal/token`（权限 0600，仅本人可读），只发送给 `mcp.mcd.cn`，`mcd logout` 即可删除；环境变量 `MCD_MCP_TOKEN` 优先。默认设置（`mcd config`）只记住门店编码、地址 ID、点餐方式、积分用法和最近的订单号（`prefs.json`），`mcd config reset` 清空。
- 发布包由 GitHub Actions 构建，附带 `SHA256SUMS`；安装脚本强制校验，校验失败就不会安装。
- 实物兑换必须明确指定收货地址。

## 业务价值

- **对用户**：点餐时不用自己比较“这张券和那点积分哪个更划算”，一句话就能拿到最省的付法；快过期的券和用剩的积分会被顺手提醒用掉。
- **对麦当劳**：唤醒沉睡积分和未使用的优惠券，把积分商城、门店活动和点餐连成一条链路，提升券的核销率、活动曝光和客单件数。
- **对 AI agent**：`--json` 和自带的 Skill 让 agent 能直接调用这套能力，同时保证每次扣积分、下单前都先征得用户同意。
- **对开发者**：提供一个接入全部 35 个工具的完整示例，以及一个不依赖 SDK 的 Streamable HTTP 客户端实现（附带与官方 SDK 的互通测试）。
