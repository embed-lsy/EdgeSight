# -*- coding: utf-8 -*-
"""
生成一张可直接 A4 打印的棋盘格标定图（EdgeSight 标定用）。

- 内角点 9 x 6（= 方格 10 列 x 7 行）
- 每格物理边长 18.0 mm（打印时必须 100% 比例，"按实际大小"）
  ※ 为什么不是 25mm：9x6 内角点 + 25mm 方格 = 棋盘宽 250mm，超过 A4 纸宽 210mm，
    打印必然被裁掉。18mm 时棋盘 180 x 126mm，A4 内留有足够白边。
- A4 = 210 x 297 mm，DPI=300 => 2480 x 3508 px
- 图下方附带 100mm 校验尺：打印后用直尺量，必须是 100mm，否则说明被缩放了

输出：与本脚本同目录的 `chessboard_A4_9x6_18mm.png`（仓库内已随附该成品图，
本脚本用于**复现/核对**它，而不是每次都必须跑）。

用法：
    python docs/gen_chessboard.py
自检：脚本末尾会对逐格宽度、棋盘总跨度、页面留白做三项断言，
      任一项不过则退出码为 1。
"""
import os
import sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# ---------- 参数 ----------
COLS_INNER = 9            # 内角点列数
ROWS_INNER = 6            # 内角点行数
SQ_MM = 18.0              # 方格物理边长 (mm) —— 必须保证 10 列 x 18mm = 180mm < 210mm
DPI = 300
MM_PER_IN = 25.4

A4_W_MM, A4_H_MM = 210.0, 297.0
PAGE_W = int(round(A4_W_MM / MM_PER_IN * DPI))   # 2480
PAGE_H = int(round(A4_H_MM / MM_PER_IN * DPI))   # 3508
PX_PER_MM = DPI / MM_PER_IN                      # 11.811...

SQ = SQ_MM * PX_PER_MM                    # 每格像素
SQUARES_X = COLS_INNER + 1                # 10
SQUARES_Y = ROWS_INNER + 1                # 7

BW = SQ * SQUARES_X                       # 棋盘宽像素
BH = SQ * SQUARES_Y                       # 棋盘高像素

print("page       :", PAGE_W, "x", PAGE_H, "px  =", A4_W_MM, "x", A4_H_MM, "mm @", DPI, "dpi")
print("square     :", round(SQ, 2), "px =", SQ_MM, "mm")
print("board      : %.1f x %.1f mm (must fit %g x %g)" % (
    BW / PX_PER_MM, BH / PX_PER_MM, A4_W_MM, A4_H_MM))
assert BW / PX_PER_MM < A4_W_MM - 20, "棋盘太宽，放不进 A4！"
assert BH / PX_PER_MM < A4_H_MM - 60, "棋盘太高，放不进 A4！"
print("inner corns:", COLS_INNER, "x", ROWS_INNER)

# ---------- 画布 ----------
img = Image.new("RGB", (PAGE_W, PAGE_H), "white")
d = ImageDraw.Draw(img)

# 棋盘左上角：水平居中，垂直略偏上（给下方留出尺子和文字）
ox = (PAGE_W - BW) / 2.0
oy = 360.0                      # 距页顶 30mm

# 画棋盘：格子 (i, j)，i 为列，j 为行；偶数格画黑
# 注意：用 round() 计算每条边的绝对坐标，避免 SQ 为小数时逐格累加产生 ±1px 漂移
for j in range(SQUARES_Y):
    for i in range(SQUARES_X):
        if (i + j) % 2 == 0:
            x0 = round(ox + i * SQ)
            y0 = round(oy + j * SQ)
            x1 = round(ox + (i + 1) * SQ) - 1
            y1 = round(oy + (j + 1) * SQ) - 1
            d.rectangle([x0, y0, x1, y1], fill="black")

# 外框：细黑线，方便看清棋盘边界
d.rectangle([round(ox) - 1, round(oy) - 1, round(ox + BW) + 1, round(oy + BH) + 1],
            outline="black", width=2)

# ---------- 打印校验尺 (100 mm) ----------
def load_font(size):
    for p in (r"C:\Windows\Fonts\msyh.ttc",
              r"C:\Windows\Fonts\simhei.ttf",
              r"C:\Windows\Fonts\arial.ttf"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()

f_big = load_font(46)
f_mid = load_font(34)
f_sml = load_font(28)

# 尺子：水平居中，位于棋盘下方
ruler_len_px = 100.0 * PX_PER_MM
rx0 = (PAGE_W - ruler_len_px) / 2.0
ry = oy + BH + 300.0

d.line([rx0, ry, rx0 + ruler_len_px, ry], fill="black", width=6)
# 每 10mm 一个刻度，每 50mm 加长
for k in range(0, 101, 10):
    xx = rx0 + k * PX_PER_MM
    h = 60 if k % 50 == 0 else 34
    d.line([xx, ry - h / 2.0, xx, ry + h / 2.0], fill="black", width=6 if k % 50 == 0 else 4)
    if k % 50 == 0:
        d.text((xx, ry + 46), str(k), font=f_sml, fill="black", anchor="ma")

d.text((PAGE_W / 2.0, ry - 90),
       "打印校验尺：这条线的两端点间距必须正好 100 mm",
       font=f_mid, fill="black", anchor="ma")

# ---------- 标题与说明 ----------
title = "EdgeSight 相机标定棋盘格    内角点 %d x %d    方格边长 %.0f mm" % (
    COLS_INNER, ROWS_INNER, SQ_MM)
d.text((PAGE_W / 2.0, 96), title, font=f_big, fill="black", anchor="ma")

notes = [
    "打印设置：纸张 A4，缩放必须选「实际大小 / 100%」，绝不能选「适应页面」。",
    "打印后用直尺量上面那条校验尺：若正好 100 mm，说明比例正确，方格就是 18 mm。",
    "若量出来不是 100 mm（例如 96 mm），实际方格边长 = 18 × 实测量/100，把实际值填进软件。",
    "把这张纸贴在硬纸板上、尽量压平；折皱或卷曲会明显拉低标定精度。",
]
ty = ry + 150
for line in notes:
    d.text((PAGE_W / 2.0, ty), line, font=f_sml, fill=(60, 60, 60), anchor="ma")
    ty += 52

# ---------- 保存 ----------
# 固定输出到脚本所在目录：避免在调用者的当前工作目录（可能是仓库根）留下文件
out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "chessboard_A4_9x6_18mm.png")
img.save(out, dpi=(DPI, DPI))
print("saved      :", out)
print("size       :", os.path.getsize(out), "bytes")

# ---------- 自检 1：逐格宽度 ----------
arr = np.array(img.convert("L"))
row_y = int(oy + SQ / 2)
x_lo = max(int(ox) - 4, 0)
x_hi = min(int(ox + BW) + 4, PAGE_W)
runs = []
prev = None
start = 0
for x in range(x_lo, x_hi):
    v = arr[row_y, x] < 128
    if prev is None:
        prev = v
        start = x
    elif v != prev:
        runs.append((prev, x - start))
        prev = v
        start = x
runs.append((prev, x_hi - start))
core = [r for r in runs if r[1] > SQ * 0.5]
lens = [r[1] for r in core]
print("self-check : black/white run lengths (px):", lens[:12])
print("self-check : expected ~", round(SQ, 2), "-> max deviation",
      round(max(abs(l - SQ) for l in lens), 2) if lens else "n/a")
ok = bool(lens) and max(abs(l - SQ) for l in lens) <= 1.5
print("self-check : per-square", "PASS" if ok else "FAIL")

# ---------- 自检 2：棋盘总跨度 ----------
w_span = round(ox + BW) - round(ox)
h_span = round(oy + BH) - round(oy)
exp_w = round(SQ * SQUARES_X)
exp_h = round(SQ * SQUARES_Y)
print("self-check : board span %d x %d px, expected %d x %d" % (w_span, h_span, exp_w, exp_h))
ok2 = abs(w_span - exp_w) <= 1 and abs(h_span - exp_h) <= 1
print("self-check : span", "PASS" if ok2 else "FAIL")
print("self-check : physical board = %.1f x %.1f mm" % (w_span / PX_PER_MM, h_span / PX_PER_MM))

# ---------- 自检 3：棋盘必须完整落在页面内，且带白边 ----------
lo_x = round(ox) - 4
hi_x = round(ox + BW) + 4
ok3 = lo_x >= 0 and hi_x <= PAGE_W
print("self-check : margins  L=%.1fmm R=%.1fmm T=%.1fmm B=%.1fmm" % (
    ox / PX_PER_MM, (PAGE_W - ox - BW) / PX_PER_MM,
    oy / PX_PER_MM, (PAGE_H - oy - BH) / PX_PER_MM))
print("self-check : inside-page", "PASS" if ok3 else "FAIL")

sys.exit(0 if (ok and ok2 and ok3) else 1)
