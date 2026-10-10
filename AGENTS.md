# 给 AI agent 的说明

想让 agent 帮用户点麦当劳、查积分和优惠券？三步就能接入：

```bash
curl -fsSL --max-time 60 https://gh-proxy.com/https://github.com/Zhangfengmo/mcd-terminal/releases/latest/download/install.sh | bash   # 海外网络去掉镜像前缀
mcd login --token <用户的 MCP Token>   # 或让用户自己运行 mcd login
mcd skill install        # 装进 Claude Code 的技能目录；其他 agent 用 --dir 指定目录
mcd skill show           # 或者直接把使用指南打印出来给 agent 读
```

Windows 用 `irm https://github.com/Zhangfengmo/mcd-terminal/releases/latest/download/install.ps1 | iex`。

完整指南：根目录的 [SKILL.md](SKILL.md)（`mcd_terminal/skill/SKILL.md` 是随程序分发的同一份副本，修改时两处保持一致，测试会检查）。

要点：

- 所有命令都加 `--json`，stdout 只输出一个 JSON 对象。
- 会扣积分或下单的命令，不加 `--yes` 只返回方案（`status: needs_confirmation`）；必须先得到用户同意，再执行返回值里的 `confirm_with`。
- 付款永远由用户自己打开 `pay_url` 完成。
- 没有 Token 时加 `--demo`。

## 在本仓库里开发

```bash
pip install -e ".[dev]" && pytest
python packaging/e2e.py python -m mcd_terminal   # 全部命令的回环测试（演示数据，约 20 秒）
```

代码结构：`client.py`（MCP 客户端）、`order.py` / `valuation.py`（纯逻辑，不做 I/O）、`ordering.py`（下单流程）、`cli.py`（命令）、`render.py`（终端界面）、`web.py` + `web/index.html`（网页版，复用 `--json` 接口）、`demo.py`（演示数据）。
