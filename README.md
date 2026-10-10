<div align="center">

# 麦麦交易终端

**帮你点麦当劳最省的 Skill**

自动叠加优惠券、积分和门店活动，算出这一单怎么付最划算。<br>
交给 AI 帮你点，或者自己在终端、浏览器里点。

[![Release](https://img.shields.io/github/v/release/Zhangfengmo/mcd-terminal?color=D97757&label=release)](https://github.com/Zhangfengmo/mcd-terminal/releases/latest)
![Platforms](https://img.shields.io/badge/macOS%20%7C%20Linux%20%7C%20Windows-x64%20%26%20arm64-4EBA65)
![MCP](https://img.shields.io/badge/麦当劳%20MCP-35%20个工具全接入-E5A84B)
[![License](https://img.shields.io/badge/license-MIT-lightgrey)](#更多)

[上手](#上手) · [能做什么](#能做什么) · [使用示例](#使用示例) · [常见问题](#常见问题)

<img src="docs/demo.gif" alt="演示：终端里一句话点餐，自动叠加券和积分，确认后下单并显示付款码；再打开网页版加购、扫码付款" width="760">

</div>

## 上手

### 方法一：交给 AI（推荐）

在 Claude Code、WorkBuddy、Cursor 等 AI agent 里发这段话，它会自己装好：

```text
帮我安装并接入「麦麦交易终端」：https://github.com/Zhangfengmo/mcd-terminal
按 README 安装 mcd 并运行 mcd skill install；然后让我去 https://open.mcd.cn/mcp 复制 Token，运行 mcd login 粘贴。
```

之后直接说需求就行，比如：

- “帮我点个巨无霸和拿铁，怎么省怎么来”
- “积分快过期了，换点什么最划算？”
- “周末给孩子办生日派对，我们 6 个人，约哪场最稳？”

扣积分、下单、抽奖、预约前，AI 都会先问你；付款由你自己扫码。

### 方法二：自己用

**1. 安装**（不需要 Python）

```bash
# macOS / Linux / WSL（国内网络；海外去掉 https://gh-proxy.com/）
curl -fsSL --max-time 60 https://gh-proxy.com/https://github.com/Zhangfengmo/mcd-terminal/releases/latest/download/install.sh | bash
```

```powershell
# Windows PowerShell（国内网络；海外去掉 https://gh-proxy.com/）
irm https://gh-proxy.com/https://github.com/Zhangfengmo/mcd-terminal/releases/latest/download/install.ps1 | iex
```

**2. 登录**：在 [麦当劳 MCP 开放平台](https://open.mcd.cn/mcp) 用手机号登录，「控制台 → 激活」复制 Token，然后：

```bash
mcd login
```

**3. 点餐**

```bash
mcd                               # 今日简报
mcd order 巨无霸 拿铁 --dry-run     # 只看怎么付最省
mcd order 巨无霸 拿铁               # 确认后下单，手机扫付款码进 App 付款
mcd web                           # 网页版
```

没有 Token 也能先体验：命令后加 `--demo`。

## 能做什么

- **点餐最省**：每样餐品在现金、已有券、积分换券里选最省的组合，下单前实时核价。支持自取、外送、得来速、团餐和预约。
- **活动和派对**：活动地图一览，活动餐品直接加购；派对按人数推荐最不怕凑不齐的场次，直接预约。
- **积分和券**：到期提醒、快过期积分换什么最值、一键领券、积分抽奖、问卷奖券。
- **吃了多少**：按真实订单统计今天、本周、本月的热量和营养。
- **提醒**：券到期、活动、派对一键加进提醒事项或日历。
- **游戏厅**：等餐时玩接薯条，餐好了自动提示取餐码；老虎机按预算和券摇出今天吃啥，每日猜价、麦麦签、麦麦人格可以分享给朋友。终端和网页都能玩。

以上功能在网页版（`mcd web`）里的样子：

<img src="docs/web-demo.gif" alt="网页版演示：活动地图里把活动餐品加进购物车；点餐页搜索加购，小票实时算出每样怎么付，单独移除一样，确认后扫码付款；派对按人数切换日期找最稳的场次；积分抽奖先确认再抽；订单页查看本月吃了多少热量；游戏厅里摇老虎机决定吃啥、玩接薯条" width="760">

## 目标用户

- 常吃麦当劳、手上攒着券和积分的人
- 用 AI agent、想让 AI 帮忙点餐的人
- 给孩子办生日会的家长，和在意吃了多少的人

## 使用示例

| 命令 | 做什么 |
| --- | --- |
| `mcd order 巨无霸 麦乐鸡x2` | 点餐（`-n` 只看不下单，`-d` 外送） |
| `mcd track` / `mcd orders` | 订单进度和取餐码 / 最近订单 |
| `mcd portfolio` / `mcd spend --expiring` | 我的积分和券 / 用掉快过期的积分 |
| `mcd party 生日派对 -c 上海 --people 6` | 派对场次和推荐，加 `--book` 预约 |
| `mcd stats` | 吃了多少热量 |
| `mcd play` | 游戏厅（`mcd play fries --wait last` 边等餐边玩） |
| `mcd config` | 默认门店、地址、点餐方式 |
| `mcd web` | 网页版 |

全部命令：`mcd -h`。

## 放心用

- 扣积分、下单、抽奖、预约前都会先问你，付款由你自己完成。
- Token 和设置只存在本机 `~/.config/mcd-terminal/`，`mcd logout` 删除 Token。
- 安装包有 SHA-256 校验，网页版只在本机运行。

## 常见问题

<details>
<summary><b>安装慢或卡住？</b></summary>

把 `gh-proxy.com` 换成 `ghfast.top` 再试；用了代理的话先 `export https_proxy=http://127.0.0.1:<端口>`。
</details>

<details>
<summary><b>提示 <code>command not found: mcd</code>？</b></summary>

重新打开终端，或执行 `export PATH="$HOME/.local/bin:$PATH"`。
</details>

<details>
<summary><b>到店自取用哪家店？</b></summary>

麦当劳 MCP 不支持 GPS 定位。默认依次用：上次的门店、App 收藏的门店、收货地址附近的门店。换店加 `--city 成都 --near 天府三街`，会记住。
</details>

<details>
<summary><b>怎么升级、卸载？</b></summary>

升级：重新运行安装命令。卸载：`mcd logout`，再删掉 `~/.local/bin/mcd`、`~/.local/share/mcd-terminal`、`~/.config/mcd-terminal`。
</details>

## 原理

给每样餐品选“现金 / 已有券 / 积分换券”，在积分预算内让实付最低，这是一个多选背包问题，引擎精确求解。演示里原价 ¥68.50 的一单，凭直觉用积分要付 ¥25.00，最优解是 ¥21.80。详见 [原理剖析](docs/how-it-works.md)。

## 更多

- 给开发者和 agent：[SKILL.md](SKILL.md) · [AGENTS.md](AGENTS.md) · [MCP_INTEGRATION.md](MCP_INTEGRATION.md)
- 欢迎提 [Issue](https://github.com/Zhangfengmo/mcd-terminal/issues/new) 或 Pull Request；觉得有用就点个 Star。
- 本项目是麦当劳程序员创意开发大赛参赛作品，非官方产品，仅供个人非商业使用（[参赛声明](CONTEST_DECLARATION.md)）。License: MIT
