"""录制 docs/web-demo.gif：网页版从活动地图加购、小票单个移除，到扫码付款。

    pip install playwright && python scripts/record_web.py      # 需要 Chromium 和 ffmpeg

全程用演示数据（--demo），不连麦当劳。先录成 webm，再用 ffmpeg 加速、剪掉下单等待、转成 GIF。
"""
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("MCD_HOME", tempfile.mkdtemp(prefix="mcd-rec-"))
os.environ.setdefault("MCD_DEMO_NOW", "2026-10-10 12:20")
os.environ.setdefault("MCD_DEMO_DELAY", "0.12")
sys.path.insert(0, str(ROOT))
from playwright.sync_api import sync_playwright  # noqa: E402

from mcd_terminal.web import serve  # noqa: E402

httpd, url = serve(demo=True, port=0, open_browser=False)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
CHROME = os.environ.get("CHROME")  # e.g. /opt/pw-browsers/chromium-1194/chrome-linux/chrome
W, H = 1280, 900
CURSOR = r"""
window.addEventListener('DOMContentLoaded', () => {
  const c = document.createElement('div');
  c.id = '__cur';
  c.innerHTML = '<svg width="26" height="26" viewBox="0 0 24 24"><path d="M4 2l15 9-6.5 1.5L9 19z" fill="#221c35" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
  Object.assign(c.style, {position:'fixed', left:'0', top:'0', zIndex:2147483647, pointerEvents:'none', transform:'translate(-4px,-2px)'});
  document.body.appendChild(c);
  const st = document.createElement('style');
  st.textContent = '.__ripple{position:fixed;width:34px;height:34px;margin:-17px 0 0 -17px;border-radius:50%;border:3px solid #ff5a36;pointer-events:none;z-index:2147483646;animation:__r .45s ease-out forwards}@keyframes __r{from{transform:scale(.3);opacity:1}to{transform:scale(1.4);opacity:0}}';
  document.head.appendChild(st);
  document.addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
  document.addEventListener('mousedown', e => { const r = document.createElement('div'); r.className='__ripple'; r.style.left=e.clientX+'px'; r.style.top=e.clientY+'px'; document.body.appendChild(r); setTimeout(()=>r.remove(),500); }, true);
});
"""
pos = [W // 2, H // 2]

def move_to(pg, loc, steps=22):
    loc.scroll_into_view_if_needed()
    box = loc.bounding_box()
    x, y = box['x'] + box['width'] / 2, box['y'] + box['height'] / 2
    pg.mouse.move(x, y, steps=steps)
    pos[:] = [x, y]

def click(pg, sel_or_loc, wait=700):
    loc = pg.locator(sel_or_loc).first if isinstance(sel_or_loc, str) else sel_or_loc
    move_to(pg, loc)
    pg.wait_for_timeout(180)
    pg.mouse.down(); pg.mouse.up()
    pg.wait_for_timeout(wait)

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROME, args=['--no-sandbox'])
    vid = tempfile.mkdtemp(prefix='mcd-vid-')
    ctx = b.new_context(viewport={'width': W, 'height': H}, device_scale_factor=1,
                        record_video_dir=vid, record_video_size={'width': W, 'height': H})
    ctx.add_init_script(CURSOR)
    pg = ctx.new_page()
    t0 = time.monotonic()                                       # video clock starts with the page
    pg.goto(url)
    pg.mouse.move(*pos)
    pg.wait_for_timeout(2600)                                   # 今日 (skeleton -> content)
    click(pg, '[data-tab=campaigns]', 2200)                      # 活动地图
    pin = pg.locator('[data-pin="3"]').first                     # 周边玩具铺 hover
    move_to(pg, pin); pg.wait_for_timeout(700)
    click(pg, '[data-pin="0"]', 1800)                            # 麦辣鸡腿堡第二份半价
    click(pg, 'dialog [data-add]', 1300)                         # 直接加入
    click(pg, 'dialog [data-close]', 600)
    click(pg, '[data-tab=order]', 1800)
    pg.wait_for_selector('[aria-label="移除一份 麦辣鸡腿堡"]', timeout=15000)
    pg.wait_for_timeout(900)
    for q, name in [('巨无霸', '巨无霸'), ('拿铁', '中杯拿铁'), ('薯条', '中份薯条'), ('麦乐鸡', '麦乐鸡 5 块')]:
        click(pg, '#search', 200)
        pg.keyboard.press('Control+A'); pg.keyboard.press('Backspace')
        pg.keyboard.type(q, delay=120)
        pg.wait_for_timeout(450)
        click(pg, pg.locator(f'article.dish:has(.name:text-is("{name}")) [data-inc]').first, 500)
    click(pg, '#search', 150)
    pg.keyboard.press('Control+A'); pg.keyboard.press('Backspace')
    pg.wait_for_selector('[aria-label="移除一份 麦乐鸡 5 块"]', timeout=15000)
    pg.wait_for_timeout(2600)
    click(pg, '[aria-label="移除一份 中份薯条"]', 0)
    pg.wait_for_function("!document.querySelector('[aria-label=\"移除一份 中份薯条\"]')", timeout=15000)
    pg.wait_for_timeout(2400)
    click(pg, '#checkoutBtn', 1600)
    click(pg, 'dialog [data-yes]', 0)
    pg.wait_for_selector('dialog .qr svg', timeout=20000)
    t_qr = time.monotonic() - t0
    pg.wait_for_selector('dialog .qr svg', timeout=20000)
    pg.wait_for_timeout(3500)
    pg.mouse.move(pos[0]+40, pos[1]+30, steps=20)
    pg.wait_for_timeout(600)
    path = pg.video.path()
    ctx.close(); b.close()
httpd.shutdown()

# 下单那段“正在下单…”只留 1.5 秒，整体 1.4 倍速，10 fps、900 宽
cut_to = t_qr - 0.4
cut_from = max(0.0, cut_to - 5.0)
out = ROOT / "docs" / "web-demo.gif"
graph = (f"[0:v]trim=0:{cut_from:.2f},setpts=PTS-STARTPTS[a];[0:v]trim=start={cut_to:.2f},setpts=PTS-STARTPTS[b];"
         "[a][b]concat=n=2:v=1[c];[c]setpts=PTS/1.4,fps=10,scale=900:-1:flags=lanczos,split[x][y];"
         "[x]palettegen=max_colors=96:stats_mode=full[p];[y][p]paletteuse=dither=none:diff_mode=rectangle")
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", path, "-filter_complex", graph, str(out)], check=True)
shutil.rmtree(vid, ignore_errors=True)
print("wrote", out)
