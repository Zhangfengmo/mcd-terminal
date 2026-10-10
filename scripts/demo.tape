# 录制 docs/demo.gif：  vhs scripts/demo.tape
# 需要 vhs（https://github.com/charmbracelet/vhs）和 Noto Sans Mono CJK 字体，且 mcd 已安装在 PATH 中。
# 网页版的录屏见 scripts/record_web.py（输出 docs/web-demo.gif）。
Output docs/demo.gif

Set Shell "bash"
Set FontSize 15
Set FontFamily "Noto Sans Mono CJK SC"
Set Width 1180
Set Height 900
Set Padding 22
Set WindowBar Colorful
Set WindowBarSize 36
Set BorderRadius 10
Set TypingSpeed 55ms
Set Theme { "name": "mcd", "background": "#1F1E1D", "foreground": "#E8E6E3", "cursor": "#D97757", "selection": "#3A3836", "black": "#1F1E1D", "red": "#FF6B80", "green": "#4EBA65", "yellow": "#E5A84B", "blue": "#7AA2F7", "magenta": "#C792EA", "cyan": "#7DCFFF", "white": "#E8E6E3", "brightBlack": "#6B6866", "brightRed": "#FF6B80", "brightGreen": "#4EBA65", "brightYellow": "#E5A84B", "brightBlue": "#7AA2F7", "brightMagenta": "#C792EA", "brightCyan": "#7DCFFF", "brightWhite": "#FFFFFF" }

Env MCD_DEMO_DELAY "0.3"
Env MCD_DEMO_NOW "2026-10-10 12:20"
Env COLORTERM "truecolor"

Hide
Type "source scripts/demo_rc.sh"
Enter
Sleep 300ms
Show

Sleep 600ms
Type "mcd --demo"
Sleep 400ms
Enter
Sleep 5s

Type "clear"
Enter
Sleep 300ms
# 点餐用短命令 mcd o，数量写 x2（zsh 里不用加引号）；中文从历史里调出（见 demo_rc.sh）
Up
Sleep 1.2s
Enter
Sleep 10s
# “顺便带上？”——剩下的积分还能免费带一个圆筒冰淇淋，手上的麦乐鸡券也提醒一下
Down
Sleep 600ms
Up
Sleep 600ms
Enter
Sleep 4s
# 确认下单：上下键选择，回车确认
Down
Sleep 700ms
Up
Sleep 700ms
Enter
Sleep 7s

# 同一个引擎的网页版
Type "clear"
Enter
Sleep 300ms
Type "mcd --demo w"
Sleep 400ms
Enter
Sleep 4s
Ctrl+C
Sleep 2s
