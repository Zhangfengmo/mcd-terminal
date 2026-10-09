#!/usr/bin/env bash
# 麦麦交易终端 安装脚本（macOS / Linux / WSL）
#
#   curl -fsSL https://github.com/Zhangfengmo/mcd-terminal/releases/latest/download/install.sh | bash
#
# 下载当前平台的发布包，强制校验 SHA-256，安装到 ~/.local/bin/mcd。
# 校验和、下载或解压任何一步失败都会直接退出，不会安装未经校验的程序。
#
# 国内网络下载 GitHub 往往很慢：脚本会同时测速 GitHub 和几个加速镜像，挑最快的下载。
# 发布时，每个安装包的 SHA-256 已经直接写在这个脚本里（见下方 EMBEDDED_SUMS），不用再
# 另外下载校验文件；镜像只提供安装包，内容若被篡改，校验不会通过，会自动换下一个来源，
# 绝不安装未经校验的文件。
#
# 国内网络连 GitHub 下载这个脚本都可能卡住，可以改用镜像地址：
#   curl -fsSL --max-time 60 https://gh-proxy.com/https://github.com/Zhangfengmo/mcd-terminal/releases/latest/download/install.sh | bash
#
# 可选环境变量：
#   MCD_VERSION       安装指定版本，例如 v0.3.1（默认最新版）
#   MCD_INSTALL_DIR   可执行文件目录（默认 ~/.local/bin）
#   MCD_MIRROR        none = 只用 GitHub；或指定一个镜像前缀，例如 https://gh-proxy.com/
#   MCD_REPO          GitHub 仓库（默认 Zhangfengmo/mcd-terminal）
#   MCD_DOWNLOAD_URL  直接指定下载地址前缀（测试用，替代 GitHub）
set -euo pipefail

# ---- 发布时由 CI 写入：本版本号和各安装包的 SHA-256（仓库里的源文件这里为空）----
# @@EMBEDDED_BEGIN@@
EMBEDDED_VERSION=""
EMBEDDED_SUMS=""
# @@EMBEDDED_END@@

REPO="${MCD_REPO:-Zhangfengmo/mcd-terminal}"
VERSION="${MCD_VERSION:-latest}"
BIN_DIR="${MCD_INSTALL_DIR:-$HOME/.local/bin}"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/mcd-terminal"

if [ -t 1 ]; then
  C_ACC=$'\033[38;2;217;119;87m'; C_OK=$'\033[32m'; C_ERR=$'\033[31m'; C_DIM=$'\033[2m'; C_OFF=$'\033[0m'
else
  C_ACC=""; C_OK=""; C_ERR=""; C_DIM=""; C_OFF=""
fi
say()  { printf '%s\n' "${C_ACC}✻${C_OFF} $*"; }
ok()   { printf '%s\n' "  ${C_OK}✓${C_OFF} $*"; }
die()  { printf '%s\n' "  ${C_ERR}✗ $*${C_OFF}" >&2; exit 1; }

# ---------------------------------------------------------------- platform
case "$(uname -s)" in
  Darwin) OS=darwin ;;
  Linux)  OS=linux ;;
  MINGW*|MSYS*|CYGWIN*) die "Windows 请在 PowerShell 里安装：irm https://github.com/${REPO}/releases/latest/download/install.ps1 | iex" ;;
  *) die "暂不支持的系统：$(uname -s)" ;;
esac

case "$(uname -m)" in
  x86_64|amd64)  ARCH=x64 ;;
  arm64|aarch64) ARCH=arm64 ;;
  *) die "暂不支持的 CPU 架构：$(uname -m)" ;;
esac
# Apple 芯片上用 Rosetta 跑的终端也装原生 arm64 版本
if [ "$OS" = darwin ] && [ "$ARCH" = x64 ] && [ "$(sysctl -n hw.optional.arm64 2>/dev/null || echo 0)" = 1 ]; then
  ARCH=arm64
fi
if [ "$OS" = linux ] && ldd --version 2>&1 | grep -qi musl; then
  die "暂不支持基于 musl 的发行版（如 Alpine），请用：pipx install git+https://github.com/${REPO}.git"
fi

ASSET="mcd-${OS}-${ARCH}.tar.gz"
# 脚本自带校验和时，固定下载与之对应的版本，避免“最新版”在安装过程中变化
USE_EMBEDDED=0
if [ -n "$EMBEDDED_SUMS" ] && { [ "$VERSION" = latest ] || [ "$VERSION" = "$EMBEDDED_VERSION" ]; }; then
  USE_EMBEDDED=1
  VERSION="$EMBEDDED_VERSION"
fi
if [ -n "${MCD_DOWNLOAD_URL:-}" ]; then
  BASE="${MCD_DOWNLOAD_URL%/}"
elif [ "$VERSION" = latest ]; then
  BASE="https://github.com/$REPO/releases/latest/download"
else
  BASE="https://github.com/$REPO/releases/download/$VERSION"
fi

# 加速镜像：前缀 + 完整的 GitHub 地址。它们只提供安装包，校验文件仍从 GitHub 获取。
DEFAULT_MIRRORS="https://gh-proxy.com/ https://ghfast.top/"
case "${MCD_MIRROR:-}" in
  none|off|0) MIRRORS="" ;;
  "")         MIRRORS="${MCD_MIRRORS-$DEFAULT_MIRRORS}" ;;
  *)          MIRRORS="$MCD_MIRROR" ;;
esac

# ---------------------------------------------------------------- tools
HAS_CURL=0
if command -v curl >/dev/null 2>&1; then
  HAS_CURL=1
  # 每个请求都有时间上限：连上了却不传数据时不会一直卡住
  fetch() { curl -fsSL --retry 1 --connect-timeout 10 --max-time 20 -o "$2" "$1"; }
  # 大文件：在终端里显示进度条；太慢（<20KB/s 持续 20 秒）就放弃，换下一个来源
  fetch_big() {
    if [ -t 2 ]; then
      curl -fL --retry 2 --connect-timeout 10 --speed-limit 20480 --speed-time 20 --progress-bar -o "$2" "$1"
    else
      curl -fsSL --retry 2 --connect-timeout 10 --speed-limit 20480 --speed-time 20 -o "$2" "$1"
    fi
  }
elif command -v wget >/dev/null 2>&1; then
  fetch() { wget -q -T 20 -t 2 -O "$2" "$1"; }
  fetch_big() { if [ -t 2 ]; then wget -q -T 20 -t 2 --show-progress -O "$2" "$1"; else wget -q -T 20 -t 2 -O "$2" "$1"; fi; }
else
  die "需要 curl 或 wget"
fi
if command -v sha256sum >/dev/null 2>&1; then
  sha256() { sha256sum "$1" | awk '{print $1}'; }
elif command -v shasum >/dev/null 2>&1; then
  sha256() { shasum -a 256 "$1" | awk '{print $1}'; }
else
  die "需要 sha256sum 或 shasum 来校验下载内容"
fi
command -v tar >/dev/null 2>&1 || die "需要 tar"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# ---------------------------------------------------------------- download + verify
say "安装麦麦交易终端（${OS}-${ARCH}）"

# 1) 校验和：发布版脚本自带；否则从 GitHub（或测试地址）获取校验文件
if [ "$USE_EMBEDDED" = 1 ]; then
  printf '%s\n' "$EMBEDDED_SUMS" > "$TMP/SHA256SUMS"
  ok "版本 ${VERSION}（校验和已内置在安装脚本中）"
else
  fetch "${BASE}/SHA256SUMS" "${TMP}/SHA256SUMS" || die "无法从 GitHub 获取校验文件：${BASE}/SHA256SUMS（网络不通时可改用镜像安装命令，见脚本开头说明）"
fi
EXPECTED="$(awk -v f="$ASSET" '{ name=$2; sub(/^\*/, "", name) } name == f { print $1 }' "$TMP/SHA256SUMS")"
[ -n "${EXPECTED}" ] || die "SHA256SUMS 里没有 ${ASSET} 的校验和（这个平台的安装包可能还没发布）"

# 2) 安装包来源：GitHub + 加速镜像，并行测速后从快到慢依次尝试
SOURCES="GitHub|$BASE/$ASSET"
for m in $MIRRORS; do
  SOURCES="$SOURCES
$(printf '%s' "$m" | sed -E 's#^https?://##; s#/.*$##')|${m%/}/$BASE/$ASSET"
done

if [ "$HAS_CURL" = 1 ] && [ "$(printf '%s\n' "$SOURCES" | wc -l)" -gt 1 ]; then
  i=0
  while IFS='|' read -r label url; do
    i=$((i + 1))
    ( speed="$(curl -sL -r 0-262143 -o /dev/null --connect-timeout 4 --max-time 6 -w '%{speed_download}' "$url" 2>/dev/null || true)"
      printf '%s|%s|%s\n' "${speed%%.*}" "$label" "$url" > "$TMP/probe.$i" ) &
  done <<EOF
$SOURCES
EOF
  wait
  RANKED="$(cat "$TMP"/probe.* 2>/dev/null | awk -F'|' '$1 ~ /^[0-9]+$/' | sort -t'|' -k1,1nr)"
  SUMMARY="$(printf '%s\n' "${RANKED}" | awk -F'|' '$1 > 0 { s = $1 + 0; u = s >= 1048576 ? sprintf("%.1f MB/s", s/1048576) : sprintf("%d KB/s", s/1024); printf "%s%s %s", sep, $2, u; sep=" · " }')"
  [ -n "${SUMMARY}" ] && ok "测速：${SUMMARY}"
  ORDER="$(printf '%s\n' "$RANKED" | awk -F'|' '$1 > 0 { print $2 "|" $3 }')"
  # 测速失败的来源也留作最后的备选
  ORDER="$(printf '%s\n%s\n' "$ORDER" "$SOURCES" | awk 'NF && !seen[$0]++')"
else
  ORDER="$SOURCES"
fi

INSTALLED_FROM=""
while IFS='|' read -r label url; do
  [ -n "$url" ] || continue
  printf '%s\n' "  ${C_DIM}↓ 从 ${label} 下载 ${ASSET}${C_OFF}"
  rm -f "$TMP/$ASSET"
  if ! fetch_big "$url" "$TMP/$ASSET"; then
    printf '%s\n' "  ${C_DIM}  ${label} 下载失败或太慢，换下一个来源${C_OFF}"
    continue
  fi
  ACTUAL="$(sha256 "$TMP/$ASSET")"
  if [ "$EXPECTED" = "$ACTUAL" ]; then
    INSTALLED_FROM="$label"
    break
  fi
  printf '%s\n' "  ${C_ERR}  ${label} 提供的文件校验不通过，已丢弃，换下一个来源${C_OFF}"
done <<EOF
$ORDER
EOF
[ -n "${INSTALLED_FROM}" ] || die "所有来源都没能下载到校验通过的 ${ASSET}，已停止安装"
ok "已下载并通过 SHA-256 校验（来源：${INSTALLED_FROM}）"

mkdir -p "$TMP/unpack"
tar -xzf "${TMP}/${ASSET}" -C "${TMP}/unpack" || die "解压失败"
[ -x "${TMP}/unpack/mcd/mcd" ] || die "安装包内容不完整"

# ---------------------------------------------------------------- install
mkdir -p "$DATA_DIR" "$BIN_DIR"
rm -rf "$DATA_DIR/mcd.new"
mv "$TMP/unpack/mcd" "$DATA_DIR/mcd.new"
rm -rf "$DATA_DIR/mcd"
mv "$DATA_DIR/mcd.new" "$DATA_DIR/mcd"
if [ "$OS" = darwin ] && command -v xattr >/dev/null 2>&1; then
  xattr -dr com.apple.quarantine "$DATA_DIR/mcd" 2>/dev/null || true
fi
ln -sf "$DATA_DIR/mcd/mcd" "$BIN_DIR/mcd"
INSTALLED="$("${BIN_DIR}/mcd" --version 2>/dev/null)" || die "安装后无法运行 ${BIN_DIR}/mcd"
ok "已安装 ${INSTALLED} → ${BIN_DIR}/mcd"

# ---------------------------------------------------------------- PATH
case ":$PATH:" in
  *":$BIN_DIR:"*) PATH_OK=1 ;;
  *) PATH_OK=0 ;;
esac
if [ "$PATH_OK" = 0 ]; then
  case "$(basename "${SHELL:-}")" in
    zsh)  RC="$HOME/.zshrc";  LINE="export PATH=\"$BIN_DIR:\$PATH\"" ;;
    bash) if [ "$OS" = darwin ]; then RC="$HOME/.bash_profile"; else RC="$HOME/.bashrc"; fi
          LINE="export PATH=\"$BIN_DIR:\$PATH\"" ;;
    fish) RC="$HOME/.config/fish/config.fish"; LINE="fish_add_path $BIN_DIR" ;;
    *)    RC="$HOME/.profile"; LINE="export PATH=\"$BIN_DIR:\$PATH\"" ;;
  esac
  mkdir -p "$(dirname "$RC")"
  if ! grep -qsF "$LINE" "$RC"; then
    printf '\n# mcd-terminal\n%s\n' "$LINE" >> "$RC"
  fi
  ok "已把 ${BIN_DIR} 加入 PATH（写入 ${RC}）"
  echo
  printf '%s\n' "  ${C_DIM}PATH 还没在当前终端生效，请重新打开终端，或执行：${C_OFF}"
  printf '%s\n' "    source $RC"
fi

echo
say "装好了！接下来："
printf '%s\n' "    mcd login     ${C_DIM}# 粘贴一次麦当劳 MCP Token${C_OFF}"
printf '%s\n' "    mcd           ${C_DIM}# 看看今天的简报${C_OFF}"
printf '%s\n' "    mcd --demo    ${C_DIM}# 还没有 Token？先用演示数据逛逛${C_OFF}"
