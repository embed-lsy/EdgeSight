# -*- coding: utf-8 -*-
"""CHARTER 闸门检查器 —— 只读、不挂 hook、不写任何文件。

为什么要有这个脚本
------------------
``AGENTS.md`` 与 ``CHARTER.md`` 多年都写着「改完手动跑一次结构校验」并给出
命令行，但那个脚本**从来不存在**（2026-10-02 核对发现）。于是这条纪律实际上
是靠记忆执行的 —— 而靠记忆执行的纪律，等同于没有纪律。本脚本把它补上。

检查什么
--------
A. **结构**：CHARTER.md 是否存在、是否还在「定位文档」的体量内（≤120 行）、
   必备章节是否齐全。这部分判的是「这份文档有没有被当成规格书用」。

B. **五条门槛判据**：能机械判的判，不能机械判的**如实报「无数据」**。

   ⚠️ 这是本脚本最要紧的一条纪律：**绝不能把「没测过」当成「通过」**。
   测距认人这类判据的输入是卷尺和真人，脚本拿不到；它必须说
   「无数据，请按 docs/验收实测.json 填」，而不是悄悄打个勾。
   想让「无数据」也算失败，加 ``--strict``。

用法
----
    python charter_check.py --root E:/GitRepos/EdgeSight
    python charter_check.py --root . --strict      # 无数据也算不过
    python charter_check.py --root . --json        # 机器可读输出

退出码：0 = 通过（或仅有「无数据」且未开 --strict）；1 = 有 FAIL。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

PASS, FAIL, NODATA = 'PASS', 'FAIL', 'NODATA'
NOTCOVERED, NA = '未覆盖', '不适用'

# ⚠️ 「未覆盖」与「无数据」的区别（2026-10-03 加，起因是远场判据）：
#   NODATA     = 这一条**整个没测**，无从判断。
#   NOTCOVERED = 这一条**测了但只测了其中一半分支**。
#     例：测距判据有两条分支（≤5 m 按 15%、>5 m 按 20%）。只测了近场 7 个点，
#     ① 会判 PASS —— 但那个 PASS 只覆盖了「近场分支」，远场分支**一个点都没有**。
#     若不加区分，报告就会显示「测距达标」，而实际上远场根本没验证过。
#     这与本脚本最要紧的那条纪律同源：**不能把「没测」说成「通过」**，
#     只差在它是「一半没测」而不是「全没测」。
#   NA         = 明确声明该分支**对本场景不适用**，且**必须写理由**。
#     「不适用」不是「免检」：没有理由的声明一律退回 NOTCOVERED，
#     不许空口跳过一条判据。

CHARTER_MAX_LINES = 120   # AGENTS.md「合格线」一节明文规定，不是本脚本自定
# CHARTER 必须有的章节（只查标题关键字，不逐字比对 —— 措辞会改，章节不能少）
# ⚠️ 这四项来自 AGENTS.md 对 CHARTER 的定义：「范围内的、明确不做的、硬约束」，
#    加上定位与成功判据。**验收不在其中** —— 验收协议在 EVALUATION.md，
#    （2026-10-02 修：初版把「验收」也算成必备章节，凭空造了一条 CHARTER
#     从未承诺过的义务，属于假红；已改为单独检查 EVALUATION.md 是否存在）
REQUIRED_SECTIONS = ('定位', '范围', '判据', '明确不做')
DATA_RELPATH = os.path.join('docs', '验收实测.json')

# 门槛（与 CHARTER「门槛判据」一节逐条对应；改门槛时**两边一起改**）
RANGING_LIMIT_NEAR = 0.15     # ≤5 m
RANGING_LIMIT_FAR = 0.20      # >5 m
RANGING_NEAR_M = 5.0
RECOG_ENROLLED_MIN = 8        # 登记者命中 ≥8/10
RECOG_STRANGER_MIN = 9        # 未登记者拒绝 ≥9/10
FPS_MIN = 15.0


def _pad(s, width=8):
    """按终端显示宽度右填充（中文占两列，`str.ljust` 按字符数算会对不齐）。"""
    w = sum(2 if ord(c) > 127 else 1 for c in s)
    return s + ' ' * max(0, width - w)


class Report:
    def __init__(self):
        self.rows = []

    def add(self, section, item, status, detail=''):
        self.rows.append((section, item, status, detail))

    def count(self, status):
        return sum(1 for r in self.rows if r[2] == status)

    @property
    def ok(self):
        return self.count(FAIL) == 0


# ---------------------------------------------------------------------------
# A. 结构
# ---------------------------------------------------------------------------

def check_structure(root, rep):
    path = os.path.join(root, 'CHARTER.md')
    if not os.path.isfile(path):
        rep.add('结构', 'CHARTER.md 存在', FAIL, f'找不到 {path}')
        return
    try:
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as e:
        rep.add('结构', 'CHARTER.md 可读', FAIL, str(e))
        return
    lines = text.splitlines()
    n = len(lines)
    rep.add('结构', f'CHARTER.md ≤ {CHARTER_MAX_LINES} 行',
            PASS if n <= CHARTER_MAX_LINES else FAIL,
            f'{n} 行' + ('' if n <= CHARTER_MAX_LINES else '（超了说明它正被当规格书用）'))

    for kw in REQUIRED_SECTIONS:
        hit = any(kw in ln for ln in lines if ln.lstrip().startswith('#'))
        rep.add('结构', f'章节「{kw}」', PASS if hit else FAIL,
                '' if hit else '缺少该章节标题')

    # 版本号：定位文档改了就该升版本，否则「定位」与「代码」谁说了算说不清
    m = re.search(r'v(\d+\.\d+(?:\.\d+)?)', text[:400])
    rep.add('结构', '带版本号', PASS if m else FAIL, m.group(0) if m else '头部未找到 vX.Y')


# ---------------------------------------------------------------------------
# B. 五条门槛判据
# ---------------------------------------------------------------------------

def _load_data(root):
    p = os.path.join(root, DATA_RELPATH)
    if not os.path.isfile(p):
        return None, f'无 {DATA_RELPATH}'
    try:
        with open(p, 'r', encoding='utf-8') as f:
            d = json.load(f)
    except (OSError, json.JSONDecodeError, ValueError) as e:
        return None, f'{DATA_RELPATH} 解析失败：{e}'
    return (d if isinstance(d, dict) else None), ''


def _nodata(rep, item, why):
    rep.add('判据', item, NODATA, why)


def check_ranging(data, why, rep):
    """① 实景测距：逐点相对误差 vs ≤15%(≤5m) / ≤20%(>5m)。"""
    item = f'① 实景测距 ≤{int(RANGING_LIMIT_NEAR * 100)}%（≤{RANGING_NEAR_M:g} m）'
    if data is None:
        return _nodata(rep, item, why)
    pts = data.get('ranging') or []
    pts = [p for p in pts
           if isinstance(p, dict) and p.get('truth_m') and p.get('read_m')]
    if not pts:
        return _nodata(rep, item, f'{DATA_RELPATH} 的 ranging 是空的')
    bad = []
    for p in pts:
        truth, read = float(p['truth_m']), float(p['read_m'])
        rel = abs(read - truth) / truth
        lim = RANGING_LIMIT_NEAR if truth <= RANGING_NEAR_M else RANGING_LIMIT_FAR
        if rel > lim:
            bad.append(f'{truth:g}m 读 {read:g}m（{rel*100:.1f}% > {lim*100:g}%）')
    rep.add('判据', item, FAIL if bad else PASS,
            '；'.join(bad) if bad else f'{len(pts)} 个采样点全部达标')

    # --- ①b 远场分支的覆盖度 -------------------------------------------
    # 上面的 PASS 只代表「已测的点都达标」，不代表「判据的两条分支都验证过」。
    # 没有远场点时必须如实说「未覆盖」，而不是让 ① 的 PASS 顺带把远场也罩住。
    far = [p for p in pts if float(p['truth_m']) > RANGING_NEAR_M]
    item_b = f'①b 远场 >{RANGING_NEAR_M:g} m 分支（{RANGING_LIMIT_FAR*100:g}% 带宽）'
    if far:
        worst = max(abs(float(p['read_m']) - float(p['truth_m'])) / float(p['truth_m'])
                    for p in far)
        rep.add('判据', item_b, PASS,
                f'{len(far)} 个远场点，最大相对误差 {worst*100:.1f}%')
        return
    decl = data.get('far_field') or {}
    reason = str(decl.get('reason') or '').strip()
    if decl.get('applicable') is False and reason:
        rep.add('判据', item_b, NA, f'声明不适用 —— {reason}')
    else:
        why_far = ('已声明不适用但未写 reason（不许空口跳过判据）'
                   if decl.get('applicable') is False
                   else f'ranging 里没有 >{RANGING_NEAR_M:g} m 的点，该分支未验证')
        rep.add('判据', item_b, NOTCOVERED, why_far)


def check_recognition(data, why, rep):
    """② 认人精度：登记者**正面 / 背面各 10 次**分别 ≥8/10、未登记者拒绝 ≥9/10。

    CHARTER 判据原文是「正面 / 背面**各**测 10 次，≥8/10 认出登记者」——
    两个视角是**两条独立判据**，不能合并成一个数：
    合成一个的话，正面 10/10 会掩盖背面 6/10。
    模板按 ``enrolled_front`` / ``enrolled_back`` 分开记；
    旧格式只填了 ``enrolled``（不区分正背）时退回单轮判定，不误报无数据。
    """
    item = '② 认人 登记者正面/背面各≥8/10 · 未登记者拒绝≥9/10'
    if data is None:
        return _nodata(rep, item, why)
    r = data.get('recognition') or {}
    st = r.get('stranger') or {}
    front, back = r.get('enrolled_front') or {}, r.get('enrolled_back') or {}
    if front or back:
        parts = [('登记者·正面', front), ('登记者·背面', back)]
    else:
        parts = [('登记者', r.get('enrolled') or {})]

    if not st.get('total') or any(not p.get('total') for _, p in parts):
        return _nodata(rep, item,
                       f'{DATA_RELPATH} 的 recognition 缺 total')
    # 模板里 hits/rejects 留空是 null —— 那也是「没测」，不能当 0 判 FAIL
    # （2026-10-02 修：初版直接 int(None) 崩了，属于脚本自己没接住空模板）
    if any(p.get('hits') is None for _, p in parts) or st.get('rejects') is None:
        return _nodata(rep, item, f'{DATA_RELPATH} 的 hits / rejects 未填')

    msgs, oks = [], []
    for label, p in parts:
        h, t = int(p['hits']), int(p['total'])
        oks.append(f'{label} {h}/{t}')
        if h < RECOG_ENROLLED_MIN:
            msgs.append(f'{label} {h}/{t} < {RECOG_ENROLLED_MIN}/{t}')
    sr, sst = int(st['rejects']), int(st['total'])
    oks.append(f'未登记者拒绝 {sr}/{sst}')
    if sr < RECOG_STRANGER_MIN:
        msgs.append(f'未登记者拒绝 {sr}/{sst} < {RECOG_STRANGER_MIN}/{sst}')
    rep.add('判据', item, FAIL if msgs else PASS,
            '；'.join(msgs) if msgs else '、'.join(oks))


def check_criteria_alignment(root, rep):
    """⑥ 判据数字：**CHARTER 写的必须与代码常量一致（以代码为准）**。

    为什么要有这条
    --------------
    判据的**真值**在 ``charter_check.py`` 顶部的常量里，``CHARTER.md`` 只是它的
    人类可读副本。副本一旦与真值漂移，就会出现「文档说一套、闸门判另一套」——
    那时闸门的绿是**假绿**：它判的是代码里的数，人看的却是文档里的数。

    （2026-10-03 加，起因：判据① 收窄后要同步 CHARTER / EVALUATION / README
    三处，靠人肉对齐必然漏 —— 这次就漏了 README 里两处「整链路 ≥15 FPS」，
    而判据早在 v1.4.3 就已收窄为「推理 FPS」。）
    """
    item = '⑥ 判据数字与代码一致（以代码为准）'
    path = os.path.join(root, 'CHARTER.md')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()
    except (OSError, UnicodeDecodeError) as e:
        rep.add('结构', item, FAIL, f'读不到 CHARTER.md：{e}')
        return

    miss = [f'缺 {s}' for s, present in (
        (f'{int(RANGING_LIMIT_NEAR * 100)}%',
         any(f'{int(RANGING_LIMIT_NEAR * 100)}%' in ln for ln in lines)),
        (f'{RECOG_ENROLLED_MIN}/10',
         any(f'{RECOG_ENROLLED_MIN}/10' in ln for ln in lines)),
        (f'{RECOG_STRANGER_MIN}/10',
         any(f'{RECOG_STRANGER_MIN}/10' in ln for ln in lines)),
        (f'{int(FPS_MIN)} FPS',
         any(f'{int(FPS_MIN)} FPS' in ln for ln in lines)),
    ) if not present]
    if miss:
        rep.add('结构', item, FAIL, '；'.join(miss) + '（按代码常量核对）')
        return

    # 远场带宽若还写着，必须**同处声明不适用** —— 防判据被悄悄改回去
    far_s = f'{int(RANGING_LIMIT_FAR * 100)}%'
    bad = [i for i, ln in enumerate(lines) if far_s in ln]
    for i in bad:
        near = lines[max(0, i - 3):i + 4]
        if not any('不适用' in ln for ln in near):
            rep.add('结构', item, FAIL,
                    f'L{i + 1} 写了 {far_s} 但周边没声明「不适用」'
                    f'（v1.5.0 已把远场分支移出判据）')
            return
    rep.add('结构', item, PASS,
            f'近场 {int(RANGING_LIMIT_NEAR * 100)}% / 认人 '
            f'{RECOG_ENROLLED_MIN}/{RECOG_STRANGER_MIN} / {int(FPS_MIN)} FPS 与代码一致')


def check_uniqueness(root, rep):
    """③ 目标唯一性：只对追踪目标出距离与 TTC。

    ⚠️ 这是**存在性检查**，不是精度检查：它只能证明「这道门还在」，
    证明不了门关得严不严。真正的验证要靠录制回放（见 ``EVALUATION.md``）。
    """
    item = '③ 目标唯一性（只对追踪目标出数）'
    mw = os.path.join(root, 'main_windows.py')
    try:
        with open(mw, 'r', encoding='utf-8') as f:
            src = f.read()
    except (OSError, UnicodeDecodeError) as e:
        rep.add('判据', item, FAIL, f'读不到 main_windows.py：{e}')
        return
    gates = [s for s in ('_identity_reject_reason', 'track_target',
                         'is_track_target') if s in src]
    rep.add('判据', item, PASS if len(gates) >= 2 else FAIL,
            f'命中 {len(gates)}/3 个身份门符号' + ('；仅结构检查，不等于精度达标' if gates else ''))


def check_fps(data, why, rep):
    """④ 推理 ≥15 FPS。"""
    item = '④ 推理 ≥15 FPS'
    if data is None:
        return _nodata(rep, item, why)
    v = data.get('fps') or {}
    f = v.get('inference_fps')
    if f is None:
        return _nodata(rep, item, f'{DATA_RELPATH} 的 fps.inference_fps 未填')
    f = float(f)
    extra = ''
    cc = v.get('concurrent_fps')
    if cc is not None and float(cc) < FPS_MIN:
        extra = f'；⚠️ 并发时 {float(cc):.1f} FPS < {FPS_MIN:g}'
    rep.add('判据', item, PASS if f >= FPS_MIN else FAIL,
            f'{f:.1f} FPS' + extra)


def check_replay(root, rep):
    """⑤ 录制回放：能录能回放 —— 直接 import 验证，比 grep 可靠。"""
    item = '⑤ 录制回放 能录能回放'
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        from core.recorder import Recorder, Replayer  # noqa: F401
        from core.recorder import FrameRecord          # noqa: F401
        rep.add('判据', item, PASS, 'core.recorder 可导入（Recorder/Replayer/FrameRecord）')
    except Exception as e:  # noqa: BLE001 - 导入失败的原因要原样报出来
        rep.add('判据', item, FAIL, f'core.recorder 导入失败：{e}')


# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description='CHARTER 闸门检查器（只读）')
    ap.add_argument('--root', default='.', help='仓库根目录')
    ap.add_argument('--strict', action='store_true',
                    help='「无数据」也算不过（发版前用）')
    ap.add_argument('--json', action='store_true', help='输出 JSON')
    a = ap.parse_args(argv)

    root = os.path.abspath(a.root)
    rep = Report()
    check_structure(root, rep)
    check_criteria_alignment(root, rep)
    data, why = _load_data(root)
    check_ranging(data, why, rep)
    check_recognition(data, why, rep)
    check_uniqueness(root, rep)
    check_fps(data, why, rep)
    check_replay(root, rep)

    if a.json:
        print(json.dumps([{'section': s, 'item': i, 'status': st, 'detail': d}
                          for s, i, st, d in rep.rows],
                         ensure_ascii=False, indent=2))
    else:
        print(f'CHARTER 闸门检查　root={root}')
        print('=' * 72)
        for s, i, st, d in rep.rows:
            print(f'  [{_pad(st)}] {s} · {i}' + (f'　{d}' if d else ''))
        print('=' * 72)
        tail = []
        for st, label in ((NODATA, '无数据'), (NOTCOVERED, '未覆盖'), (NA, '不适用')):
            c = rep.count(st)
            if c:
                tail.append(f'{label} {c}')
        print(f'  PASS {rep.count(PASS)}　FAIL {rep.count(FAIL)}'
              + ('　' + '　'.join(tail) if tail else ''))
        nd = rep.count(NODATA) + rep.count(NOTCOVERED)
        if nd:
            print(f'  ⚠️ {nd} 项没测全：填 {DATA_RELPATH} 后重跑'
                  + ('（--strict 下视为不过）' if a.strict else '（当前不计 FAIL）'))
        for _, i, st, d in rep.rows:
            if st == NA:
                print(f'  ℹ️ {i} 声明不适用 —— 这是**范围限定，不是达标**，'
                      f'对外报数时须带上该限定')
        print(f'  结论：{"通过" if rep.ok and not (a.strict and nd) else "未通过"}')

    failed = not rep.ok or (a.strict and (rep.count(NODATA) + rep.count(NOTCOVERED)) > 0)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
