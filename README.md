<div align="center">

# 🍟 麦麦交易终端

**帮你点麦当劳最省的 Skill**

自动叠加优惠券、积分和门店活动，实时核价，算出这一单怎么付最划算；<br>
活动地图、派对预约、积分抽奖、热量统计也都在这里。让 AI 帮你点，或者自己在终端、浏览器里点，都行。

[![Release](https://img.shields.io/github/v/release/Zhangfengmo/mcd-terminal?color=D97757&label=release)](https://github.com/Zhangfengmo/mcd-terminal/releases/latest)
![Platforms](https://img.shields.io/badge/macOS%20%7C%20Linux%20%7C%20Windows-x64%20%26%20arm64-4EBA65)
![MCP](https://img.shields.io/badge/麦当劳%20MCP-35%20个工具全接入-E5A84B)
[![License](https://img.shields.io/badge/license-MIT-lightgrey)](#更多)

[快速开始](#快速开始) · [最近更新](#最近更新) · [网页版](#网页版mcd-web) · [功能](#功能) · [原理剖析](#原理剖析) · [作为 Skill 使用](#作为-skill-使用) · [使用示例](#使用示例) · [常见问题](#常见问题) · [反馈与参与](#反馈与参与)

<img src="docs/demo.gif" alt="演示：终端里 mcd o 一句话点餐（麦乐鸡x2），自动叠加券和积分、顺手用快过期的积分带个冰淇淋，确认后下单；再敲 mcd w，浏览器打开网页版：活动地图里直接加购、小票实时算账、单个移除、扫码付款" width="760">

</div>

## 快速开始

**1. 安装**（一行命令，不需要 Python）

```bash
# macOS / Linux / WSL · 国内网络
curl -fsSL --max-time 60 https://gh-proxy.com/https://github.com/Zhangfengmo/mcd-terminal/releases/latest/download/install.sh | bash

# macOS / Linux / WSL · 海外网络
curl -fsSL --max-time 60 https://github.com/Zhangfengmo/mcd-terminal/releases/latest/download/install.sh | bash
```

```powershell
# Windows PowerShell · 国内网络（海外网络去掉 https://gh-proxy.com/ 前缀）
irm https://gh-proxy.com/https://github.com/Zhangfengmo/mcd-terminal/releases/latest/download/install.ps1 | iex
```

**2. 登录**：在 [麦当劳 MCP 开放平台](https://open.mcd.cn/mcp) 用手机号登录，点「控制台 → 激活」复制 Token，然后：

```bash
mcd login
```

**3. 开始用**

```bash
mcd                                   # 今日简报
mcd order 巨无霸 中杯拿铁 --dry-run     # 看看怎么付最省（不下单）
```

想省事可以先把默认设置好，之后点餐什么都不用填。不设也行：第一次到店自取时会依次用你在 App 里收藏的门店、上次点餐的门店、收货地址附近的门店，选过一次就记住（麦当劳 MCP 不支持按 GPS 定位找店，想换店用 `--near 地标`）：

```bash
mcd config store --city 上海 --near 人民广场   # 默认门店
mcd config mode delivery                      # 默认外送（需要先 mcd address add 加一个地址）
mcd config                                    # 看看现在的设置
```

还没有 Token？所有命令都可以加 `--demo`，用演示数据先逛一圈。

## 最近更新

**v0.5 · 麦当劳 MCP 的 35 个工具全部接入**

- 💳 **付款码直达 App 收银台**：支付页上的二维码其实指向 `m.mcd.cn/mcp/jumpToApp`，我们直接画这个码——手机相机或微信扫一下就进麦当劳 App 付款，不用“扫码再扫码”；终端下单后也直接在终端里画出二维码。
- 🎈 **派对预约，不怕凑不齐**：`mcd party <名字> --people 4 --book`。每场显示已报几人、拉人截止倒计时，按你们的人数推荐最稳的场次（人够包场、人不够选快成团的拼团）；订完给你一段拉人文案和截止前提醒。
- 🔥 **吃了多少**：`mcd stats` 和网页版订单页，今天 / 本周 / 本月的热量、蛋白质、脂肪、碳水、钠和花费，最近 30 天每日热量。
- 🎰 **积分抽奖**：`mcd draw` 先告诉你这次扣多少积分或次数，确认后只抽一次。
- 🏢 **团餐凑满减**：`mcd order … --group` 按所选助餐服务套上满折，告诉你再加多少到下一档、加哪样刚好够。
- 🎟 **问卷奖券**：`mcd survey` 找出吃完填问卷送的券、有效期和是否用过。
- 🖼 **网页版焕新**：原创贴纸风矢量插画代替缺图时的 emoji；派对弹窗改成左图右场次、日期横向切换；共用一个 MCP 会话并缓存只读结果，切换页面明显更快。

完整变更见 [Releases](https://github.com/Zhangfengmo/mcd-terminal/releases)。

## 网页版：mcd web

终端不够直观的时候，运行 `mcd web`（或 `mcd w`），浏览器里会打开同一套功能：

<img src="docs/web-map.jpg" alt="活动地图：活动按类型落在不同的小岛上，带周边和玩具的活动有标记" width="760">

- **活动地图**：麦当劳的活动按类型分布在上新广场、优惠大街、早餐小镇、咖啡山丘、派对乐园和周边玩具铺几座小岛上，今天在做的、即将开始的一眼就能看出来；**带周边或玩具的活动单独标出**。点开活动，活动里的餐品可以**直接加进购物车**（这家店没有或卖完了，会提示换门店）。
- **积分抽奖**：路尽头的摩天轮就是奖池，看得到每样奖品；点“抽一次”会先告诉你扣多少，确认后才抽。
- **点餐**：门店菜单带图片，点几下加进购物车，右边的小票实时算出每样怎么付最省，**每一样都能单独移除**，确认后下单，**手机扫码直接进 App 付款**，再看出餐进度和取餐码。
- **我的券和积分**：按到期时间排的倒计时，快过期的标红；抽中的奖品也在这里。
- **积分商城**：商品按“每积分值多少钱”排好，一键算清仓方案。
- **订单**：最近点过的单、出餐进度、问卷送的券，以及最上面的“吃了多少”统计。
- **我的设置**：右上角能看到现在用的是哪家门店、送到哪个地址；点餐方式、门店、收货地址、积分用法、堂食外带都在这里改。新增地址会先检查手机号、城市和门牌号，同一个地址不会重复添加。

**派对和体验活动**：生日派对、亲子读书会、品鉴会、体验营。拼团在截止前凑不够最少人数会**自动取消并退款**，还要**提前 3 天预订**——所以每个场次都标出已报几人、拉人截止还剩多久；告诉它你们几个人，它会标出最稳的一场。订完给你一段能直接发到亲友群的拉人文案。

<img src="docs/web-party.jpg" alt="派对弹窗：左边是活动图片和介绍，右边是规则提示、人数选择、日期切换和当天的场次卡片，最稳的一场标绿" width="760">

**吃了多少**：把点餐记录和麦当劳官方营养表对上（套餐拆成单品算），今天 / 本周 / 本月的热量和三大营养素、钠和花费，最近 30 天每天的热量，参考线是成年人每天约 2000 千卡。

<img src="docs/web-stats.jpg" alt="热量统计：本周热量主数字、能量来源占比、最近 30 天每日热量柱状图和热量来源排行" width="760">

<img src="docs/web-demo.gif" alt="网页版演示：在活动地图上点开活动，直接把活动餐品加进购物车；到点餐页搜索加购，右边小票实时算出每样用券、用积分还是付现金；在小票里单独移除一样；确认后扫码付款" width="760">

<sub>录屏：活动地图里直接加购活动餐品 → 搜索加购 → 小票里单独移除一样 → 确认下单、扫码付款（演示数据）。重录全部演示：`scripts/make_demo.sh`</sub>

**不错过任何一个日子**：活动、券和积分到期、派对场次，都可以一键“提醒我”。在 Mac 上直接加进系统的**提醒事项**（列表「麦麦提醒」）；在 Windows 和 Linux 上生成一个带闹钟的日历文件，用 Outlook、系统日历打开就能导入。终端里也一样：

```bash
mcd remind coupons                     # 7 天内到期的券，到期当天 10 点提醒
mcd remind points                      # 快过期的积分，月底前 3 天提醒
mcd remind campaign -t 麦旋风          # 某个活动，下一个活动日提醒
mcd party 生日派对 -c 上海 --people 6   # 哪天哪场最稳；订完会提示设“拉人截止”提醒
```

网页只在你自己的电脑上运行（只监听 127.0.0.1），Token 不会发给网页；扣积分、抽奖、下单、预约前一样会先问你。没有 Token 可以先用 `mcd web --demo` 看看。

## 功能

| | |
| --- | --- |
| 🧮 **一句话点餐，自动最省** | 每样东西是付现金、用已有的券，还是先用积分兑一张，全部比一遍，选出实付最低的组合。演示里原价 ¥68.50 的一单，叠加 2 张券和 1,700 积分后只要 ¥21.80 |
| 🔍 **实时核价** | 下单前向门店报价，配送费、第二份半价、团餐折扣都以麦当劳服务端为准 |
| 💳 **扫一下就付** | 付款码直接指向麦当劳 App 的收银台，终端里、网页上都能直接扫；手机上还能一键拉起 App |
| 🔥 **吃了多少一目了然** | `mcd stats` 和网页版订单页：把点餐记录和官方营养表对上，套餐拆成单品算，今天 / 本周 / 本月的热量和三大营养素、最近 30 天走势 |
| 🏢 **团餐凑满减** | `--group` 给团队订餐时，自动套上门店的满减/满折，算出这单省多少、再加 ¥X 就到下一档、加哪样刚好够 |
| 🎈 **派对不怕凑不齐，抽奖先说清楚** | 拼团截止前凑不够人会自动取消、还要提前 3 天订——按你们的人数挑最稳的场次，显示已报几人和拉人倒计时，订完给你拉人文案和截止提醒；积分抽奖先告诉你这次扣多少，确认后只抽一次；问卷送的券也帮你找出来 |
| 🎁 **顺手提醒“不加白不加”的** | 快过期却没用上的券、用剩的积分正好够换一个冰淇淋、第二份半价……问你要不要顺便带上，加上后重新计算 |
| ☀️ **每天打开看一眼** | 直接输入 `mcd`：积分和券的到期提醒、可以领的券、今天的活动，还会推荐一份适合这个时间的餐 |
| ⏳ **不让积分白白过期** | `mcd spend --expiring` 把快过期的积分凑成最值的兑换组合；`mcd market` 告诉你一积分值几分钱 |
| 📍 **记得你的习惯** | 门店、地址、点餐方式和积分用法存成默认设置（`mcd config`），不用每次都填；同一个地址不会重复添加。支持到店自取、麦乐送、得来速、企业团餐和预约 |
| ⏰ **不错过日子** | 券和积分到期、活动开始、派对当天和拉人截止，一键放进 Mac 的提醒事项或 Windows / Linux 的日历 |
| 🔌 **35 个 MCP 工具全接入** | 积分、券、点餐、订单、团餐、派对、抽奖、问卷、营养……每个工具都有对应的命令和网页入口，见 [MCP_INTEGRATION.md](MCP_INTEGRATION.md) |

## 原理剖析

一句话点餐背后，是十几次麦当劳 MCP 调用加一个组合优化：

```mermaid
%%{init: {"flowchart": {"wrappingWidth": 320}}}%%
flowchart LR
    A["你：mcd order<br/>巨无霸 拿铁 薯条 麦乐鸡"] --> B["收集信息<br/>门店 · 菜单 · 已有券<br/>积分 · 积分商城 · 活动"]
    B --> C["优化<br/>每件商品选：现金 /<br/>已有券 / 积分兑券"]
    C --> D["实时核价<br/>门店活动 · 配送费"]
    D --> E["加购建议<br/>快过期的券 · 剩余积分"]
    E --> F{"你确认？"}
    F -- 好 --> G["兑换积分 → 下单<br/>→ 付款码（直达 App 收银台）"]
    F -- 先不了 --> H["什么都不发生"]
```

**为什么要算，而不是凭直觉？** 演示里这单原价 ¥68.50，手上有 1,880 积分和两张券（薯条、麦乐鸡）：

| 付法 | 实付 |
| --- | --- |
| 只用券 | ¥63.80 |
| 直觉：积分先换“每积分最值钱”的（拿铁、薯条、麦乐鸡），券浪费了 | ¥25.00 |
| **最优**：积分换巨无霸和拿铁，薯条、麦乐鸡用券 | **¥21.80** |

券和积分要放在一起考虑，局部最划算不等于整单最划算。引擎把它建模成带约束的多选背包问题，精确求解，并和暴力枚举对拍了 300 组随机购物车。模型、算法、AI 调用时序和安装安全链路的完整说明，见 **[原理剖析](docs/how-it-works.md)**。

## 目标用户

- **常吃麦当劳、手上攒着券和积分的人**：不用再自己算哪张券配哪样、积分该换什么，也不会让它们过期浪费。
- **用 AI agent 的人**：装上这个 Skill，让 Claude Code、WorkBuddy 等 agent 帮你点餐。最优付法由引擎精确计算，不靠 AI 心算；扣积分、下单前都会先征得你的同意。
- **喜欢在终端里解决问题的程序员**：写着代码，一条命令就把午饭点了。
- **给孩子办生日会的家长**：哪家店哪天哪场还能约、会不会凑不齐人，一眼看清，订完拉人文案也写好了。
- **在意吃了多少的人**：每周、每月从麦当劳摄入了多少热量和营养，按真实订单算。

## 作为 Skill 使用

仓库根目录的 [SKILL.md](SKILL.md) 就是这个 Skill，它告诉 agent 什么时候用、怎么调用引擎、怎么向你确认。装好之后，直接对 agent 说“帮我点个巨无霸和拿铁，怎么省怎么来”就行。

| 你的 agent | 怎么装 |
| --- | --- |
| Claude Code | `mcd skill install`（装到 `~/.claude/skills/mcd-terminal/`） |
| 其他支持 Skill 的 agent | `mcd skill install --dir <它的技能目录>`，或直接复制 `SKILL.md` |
| 不支持 Skill 的 agent | 让它先运行 `mcd skill show` 读一遍使用指南 |

agent 调用时都加 `--json`，输出单个 JSON 对象。会扣积分或下单的命令，不加 `--yes` 只返回方案，必须先得到你的同意。开发细节见 [AGENTS.md](AGENTS.md)。

## 使用示例

| 命令 | 做什么 |
| --- | --- |
| `mcd` | 今日简报 |
| `mcd order 巨无霸 麦乐鸡x2` | 点餐，自动叠加券、积分和门店活动（数量写 `x2` 或 `2份`） |
| `mcd order 巨无霸 --dry-run` | 只看怎么付最省，不下单 |
| `mcd order 巨无霸 --delivery` | 麦乐送外送到家，先用 `mcd address add` 加一个收货地址（`--drive` 得来速，`--group` 团餐，`--at "2026-10-10 12:00"` 预约） |
| `mcd order 巨无霸 --near 人民广场 --city 上海` | 换一家门店，以后会记住 |
| `mcd web` | 网页版：看活动、带图点餐、扫码付款 |
| `mcd prizes` / `mcd draw` | 积分抽奖的奖池和我抽中的奖品；`draw` 先告诉你扣多少，确认后抽一次 |
| `mcd events` / `mcd party <名字> --people 4 --by 2026-10-24` | 生日派对、亲子活动、品鉴会：每场已报几人、拉人截止还剩多久，按人数和日子挑最不怕“凑不齐”的场次 |
| `mcd party <名字> --book` | 一步步选场次、包场/拼团和人数，确认后预约、扫码付款，生成拉人文案 |
| `mcd survey` | 吃完填的满意度问卷送了什么券、还能不能用 |
| `mcd stats` | 今天、本周、本月从麦当劳吃了多少：热量、蛋白质、脂肪、碳水、钠和花费，最近 30 天每天的热量 |
| `mcd order 巨无霸x10 --group` | 企业团餐：自动套上满减/满折，告诉你再加多少能到下一档 |
| `mcd remind coupons\|points\|campaign` | 把到期日和活动放进提醒事项（Mac）或日历（Windows / Linux） |
| `mcd config` | 默认门店、收货地址、点餐方式、积分用法，设一次就行 |
| `mcd track` | 刚才那单做到哪了，显示取餐码 |
| `mcd orders` / `mcd cancel` | 最近点过什么；取消刚下的单（会先问你） |
| `mcd menu 薯条` / `mcd nutrition` | 菜单、价格和热量 |
| `mcd portfolio` | 我的积分和优惠券 |
| `mcd spend --expiring` | 把快过期的积分换成吃的 |
| `mcd claim` | 一键领取麦麦省的券 |
| `mcd calendar` | 最近有什么活动 |

**懒得打全称？** 常用命令和参数都有简写，`mcd -h` 随时查：

```bash
mcd o 巨无霸 麦乐鸡x2 -n      # = mcd order 巨无霸 麦乐鸡x2 --dry-run
mcd o 巨无霸 -d -y            # 外送，跳过确认直接下单
mcd t                         # = mcd track
```

| 简写 | 全称 | | 简写 | 全称 |
| --- | --- | --- | --- | --- |
| `o` | `order` | | `-n` | `--dry-run` 只看不下单 |
| `m` | `menu` | | `-d` / `-p` | `--delivery` 外送 / `--pickup` 自取 |
| `t` | `track` | | `-y` | `--yes` 跳过确认 |
| `p` / `s` | `portfolio` / `spend` | | `-c` / `-l` | `--city` 城市 / `--near` 附近 |
| `st` / `n` / `cal` | `stores` / `nutrition` / `calendar` | | `-j` | `--json` |
| `c` / `w` | `config` / `web` | | `-h` | `--help` |

## 放心用

- **扣积分、下单、抽奖、预约派对和取消订单前都会先问你**，付款始终由你自己扫码完成。
- **抽奖一次只抽一次**：先展示这次扣多少积分或次数，不试抽、不连抽。
- **默认设置只存在本机** `~/.config/mcd-terminal/prefs.json`：门店编码、地址 ID 和几项偏好，不含 Token，`mcd config reset` 清空。
- **Token 只留在你的电脑上**：保存在 `~/.config/mcd-terminal/token`（仅本人可读），只发送给麦当劳 MCP，`mcd logout` 即可删除。
- **安装包强制校验**：每个安装包的 SHA-256 在发布时就写进了安装脚本，下载、校验或解压任何一步失败都不会安装。
- **点餐记录也只存在本机** `~/.config/mcd-terminal/meals.json`，用来统计热量；不想要直接删掉。
- 网页版会短暂记住查询结果（菜单、商城、活动等，几十秒到几分钟），下单、兑换、抽奖、预约之后立刻清空，不会拿旧数据下单。
- 积分估值、热量和派对的已报人数 / 截止时间都是推算，仅供参考，实际以门店和 App 为准。

## 常见问题

<details>
<summary><b>安装时卡住没反应，或者下载很慢？</b></summary>

国内访问 GitHub 下载经常很慢，所以国内请用带 `gh-proxy.com` 的那条命令。安装脚本还会同时测速 GitHub 和几个加速镜像，从最快的下载并显示进度条，哪个来源卡住就自动换下一个。镜像只提供安装包，文件若被篡改，校验通不过会被丢弃。

不同地区、不同运营商能用的镜像不一样。如果 `gh-proxy.com` 在你的网络里连不上，把命令里的 `https://gh-proxy.com/` 换成 `https://ghfast.top/` 再试。如果你用了代理工具，记得终端默认不走代理，需要先 `export https_proxy=http://127.0.0.1:<端口>`。
</details>

<details>
<summary><b>装好了，但提示 <code>command not found: mcd</code>？</b></summary>

程序装在 `~/.local/bin/mcd`（Windows 是 `%LOCALAPPDATA%\mcd-terminal`），安装脚本已经把它写进了 PATH，但对已经打开的终端不起作用。重新打开一个终端，或者执行 `export PATH="$HOME/.local/bin:$PATH"`。
</details>

<details>
<summary><b>怎么升级、卸载？还有别的安装方式吗？</b></summary>

- 升级：重新运行一次安装命令。
- 卸载：`mcd logout` 删除 Token，然后删掉 `~/.local/bin/mcd`、`~/.local/share/mcd-terminal` 和 `~/.config/mcd-terminal`。
- 只用 GitHub、不走镜像：在 `bash` 前加 `MCD_MIRROR=none`。
- 用 Python 安装：`pipx install git+https://github.com/Zhangfengmo/mcd-terminal.git`。
- 想先看看安装脚本的内容：把命令里的 `| bash` 去掉。
</details>

<details>
<summary><b>到店自取是按定位找门店吗？</b></summary>

不是。麦当劳 MCP 找门店只支持“收藏的门店”和“城市 + 地点关键词”，不支持 GPS。没指定门店时，会依次用：你设过或上次用过的门店 → App 里收藏的门店 → 上次自取订单的门店 → 收货地址附近的门店。想换一家，加 `--city 成都 --near 天府三街`，或者 `mcd config store` 设成默认。
</details>

<details>
<summary><b>付款码扫了会去哪？</b></summary>

麦当劳返回的支付链接（`m.mcd.cn/mcp/scanToPay`）是给电脑看的页面，页面上的二维码指向 `m.mcd.cn/mcp/jumpToApp`：手机扫它会打开麦当劳 App 的这笔订单并直接弹出收银台。我们画的就是这个码，用相机或微信扫都行；扫不了也可以点“在这台电脑上打开付款页”。
</details>

<details>
<summary><b>热量是怎么算的？准吗？</b></summary>

用的是麦当劳官方营养表（`list-nutrition-foods`），按订单里的每样餐品查；套餐按它的组成拆开。营养表里查不到的餐品会单独列出来，不会瞎估。取消、退款和没付款的订单不算。服务端只返回最近的订单，所以每次统计都会记到本机，时间越长周、月数据越完整。
</details>

<details>
<summary><b>派对的“已报几人”和“拉人截止”是哪来的？</b></summary>

服务端只给每个场次的最少人数、最多人数和剩余位置，已报人数按“最多 − 剩余”推算；截止时间按活动须知里的“提前 N 天预订”推算（通常 3 天）。如果服务端还列着一个已经不满 N 天的场次，会提示“可能约不上”。都以 App 为准。
</details>

<details>
<summary><b>想在其他 MCP 客户端里直接接入麦当劳 MCP？</b></summary>

参考 [mcp-config.example.json](mcp-config.example.json)，Token 用环境变量 `MCD_MCP_TOKEN` 提供。本项目用到了哪些 MCP 能力，见 [MCP_INTEGRATION.md](MCP_INTEGRATION.md)。
</details>

## 反馈与参与

非常欢迎提 [Issue](https://github.com/Zhangfengmo/mcd-terminal/issues/new)，哪怕只是一句话：

- 🐛 **用着不顺**：报错、算出来的价格和门店对不上、哪一步让你犹豫了，都可以说。贴上命令和输出会更好排查（记得把 Token、手机号和地址遮掉）。
- 💡 **想要新功能**：比如想让它记住你的口味、支持某种点餐方式，或者希望 AI agent 能多做哪一步。
- 🍟 **分享你的省钱方案**：用它省下了多少、有什么券和积分的组合是它没想到的，都欢迎来聊。

也欢迎直接提 Pull Request。如果它帮你省了钱，点个 ⭐ 就是最好的鼓励。

## 更多

- [MCP_INTEGRATION.md](MCP_INTEGRATION.md)：用到的麦当劳 MCP Server、35 个工具、调用流程、真实服务端的兼容细节和业务价值
- [SKILL.md](SKILL.md) · [AGENTS.md](AGENTS.md)：给 AI agent 的使用指南
- 本项目是麦当劳程序员创意开发大赛的参赛作品，并非麦当劳官方产品，仅供个人非商业使用。参赛声明见 [CONTEST_DECLARATION.md](CONTEST_DECLARATION.md)。
- License: MIT
