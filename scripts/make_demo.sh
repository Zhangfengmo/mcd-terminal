#!/usr/bin/env bash
# 重录 README 里的两段演示（全程演示数据，不连麦当劳）：
#   docs/demo.gif      顶部演示：终端点餐 → mcd w → 浏览器里的网页版
#   docs/web-demo.gif  「网页版」一节：活动地图加购 → 小票单个移除 → 扫码付款
# 需要 vhs、ffmpeg、Noto Sans Mono CJK 字体、playwright（Chromium），mcd 已在 PATH 中。
set -euo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# 1. 终端部分
sed "s#^Output docs/demo.gif#Output \"$tmp/term.mp4\"#" scripts/demo.tape > "$tmp/term.tape"
vhs "$tmp/term.tape"

# 2. 网页部分（顺带写出 docs/web-demo.gif）
MCD_WEBM_OUT="$tmp/web.webm" "${PYTHON:-python3}" scripts/record_web.py
read -r cut_from cut_to hero_end < "$tmp/web.cut"

# 3. 拼起来：网页画面放进同色背景的“窗口”里，1.6 倍速，剪掉下单等待，交叉淡入；README 里按 760 宽显示，输出 960 宽
term_len=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$tmp/term.mp4")
ffmpeg -v error -y -i "$tmp/term.mp4" -i "$tmp/web.webm" -filter_complex "
[0:v]fps=10,format=yuv444p,settb=1/1000[t];
[1:v]trim=0:${cut_from},setpts=PTS-STARTPTS[w1];
[1:v]trim=start=${cut_to}:end=${hero_end},setpts=PTS-STARTPTS[w2];
[w1][w2]concat=n=2:v=1[w];
[w]setpts=PTS/1.6,fps=10,scale=1100:-1:flags=lanczos,pad=1180:900:40:(900-ih)/2+14:color=0x1F1E1D,format=yuv444p,settb=1/1000[wp];
[t][wp]xfade=transition=fade:duration=0.5:offset=$(python3 -c "print(round(${term_len}-0.6,2))")[v];
[v]scale=960:-1:flags=lanczos,split[x][y];[x]palettegen=max_colors=128:stats_mode=full[p];[y][p]paletteuse=dither=none:diff_mode=rectangle
" docs/demo.gif
ls -la docs/demo.gif docs/web-demo.gif
