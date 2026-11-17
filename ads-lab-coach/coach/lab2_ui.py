"""Adapt evidence to the original experiment guide; no separate page design."""
import copy
import math
from pathlib import Path
import streamlit as st
from . import capture, lab2


def instructions(p):
    z, load, f = p['z0'], p['zl'], p['f0_ghz']
    zt = math.sqrt(z*load)
    sweep = f'Start={.1*f:g} GHz、Stop={3*f:g} GHz、Step={.01*f:g} GHz'
    return [
        f'新建原理图（建议命名 lab2）。放入 1 段 TLIN，Z={z:g} Ω、E=90°、F={f:g} GHz；两端接 Term，Num=1/2、Z 都为 {z:g} Ω，参考端接 GROUND。放置 S-Param，{sweep}。Ctrl+S 保存并运行仿真。',
        f'保留 Term1（Num=1、Z={z:g} Ω），删除 Term2。短路：将 TLIN 远端直接接 GROUND；开路：去掉远端接地，使其悬空。TLIN 保持 Z={z:g} Ω、E=90°、F={f:g} GHz。两种状态分别保存并仿真，等待本步骤显示对应结果已留存后再切换。不要把 Term 参考阻抗设为 0 Ω。',
        f'恢复 Term2，Num=2、Z={load:g} Ω，参考端接地；Term1 保持 {z:g} Ω。只保留单段 Z={z:g} Ω、E=90°、F={f:g} GHz 的 TLIN。保存并仿真，读取 {f:g} GHz 处 S11 和驻波比。',
        f'在测试线与 Term2 之间串联第二段 TLIN，Z={zt:.5g} Ω、E=90°、F={f:g} GHz。Term1 保持 {z:g} Ω，Term2 保持 {load:g} Ω，后者表示负载。也可以仅保留变换线。保存并仿真。',
        f'设置 {sweep}，在匹配电路中保存并仿真。查看 S11、S21，助手读取 {f:g} GHz 处结果，计算 S11<-20 dB 的匹配带宽。同一次合格仿真可以同时完成第 4、5 步。',
    ]


def prepare(exp, p):
    exp = copy.deepcopy(exp)
    z, load, f = p['z0'], p['zl'], p['f0_ghz']
    zt = math.sqrt(z*load)
    gamma = abs((load-z)/(load+z))
    s11 = lab2.db20(gamma)
    vswr = (1+gamma)/(1-gamma)
    for step, action in zip(exp['steps'], instructions(p)):
        step['action'] = action
    exp['steps'][0]['why'] = '明确端口参考阻抗和扫频范围后，才能验证匹配、传输和相位。'
    exp['steps'][1]['ui_path'] = '删除 Term2；在 TLIN 远端添加或删除 GROUND，分别保存并仿真。'
    exp['steps'][2].update(title=f'加入 {load:g} Ω 负载，记录失配', why=f'理论 |Γ|={gamma:.5g}，S11={s11:.3f} dB，VSWR={vswr:.4g}。', ui_path=f'双击 Term2，将 Z 设为 {load:g} Ohm。')
    exp['steps'][3]['key_params'] = f'Zt=√(Z0·ZL)={zt:.5g} Ω；E=90°、F={f:g} GHz。'
    exp['steps'][3]['why'] = f'四分之一波长线将负载变换为 Zt²/ZL={z:g} Ω。'
    exp['metrics'][1]['label'] = f'{z:g} Ω 微带线宽'
    exp['expected'] = f'未匹配时 {f:g} GHz 处 S11 约 {s11:.3f} dB、VSWR 约 {vswr:.4g}；加入 {zt:.5g} Ω 变换线后，S11 应低于 -20 dB，S21 接近 0 dB。'
    cps = {cp['id']: cp for cp in exp['checkpoints']}
    cps['cp_tlin_setup']['title'] = f'TLIN、两个 Term（Num=1/2、Z={z:g} Ω）及 S-Param 设置正确'
    cps['cp_unmatched'].update(title=f'未匹配时 {f:g} GHz 处 S11（dB）', min=s11-1, max=s11+1, pass_msg=f'与理论 {s11:.3f} dB 一致', on_high=[f'核对 Term2={load:g} Ω、Term1={z:g} Ω。'], on_low=['确认还没有加入变换线。'])
    cps['cp_matched_s11'].update(title=f'匹配后 {f:g} GHz 处 S11（dB）', on_high=[f'核对变换线 Z={zt:.5g} Ω、E=90°、F={f:g} GHz。'])
    cps['cp_s21']['title'] = f'{f:g} GHz 处 S21（dB）'
    cps['cp_quarter_len']['on_fail'] = ['确认基板 εr、h 和工作频率与当前网页参数一致。']
    exp['demo']['pitch'] = [f'本实验在 {f:g} GHz 验证传输线的阻抗变换。', f'{load:g} Ω 负载接到 {z:g} Ω 系统时 S11 约 {s11:.3f} dB；加入 {zt:.5g} Ω 变换线后改善匹配。', '偏离中心频率后匹配变差，说明变换器具有带宽限制。']
    return exp


def select_cell(workspace):
    cells = sorted({s.parent.parent.name for s in Path(workspace).glob('*/*/schematic/sch.oa')})
    if 'lab2' in cells:
        return 'lab2'
    matches = [c for c in cells if c.lower().startswith(('lab2', 'exp02', 'exp2'))]
    if len(matches) == 1:
        return matches[0]
    net = Path(workspace) / 'netlist.log'
    if net.exists():
        from . import ads_watch
        candidate = ads_watch._cell_name(ads_watch._top_design(net))
        if candidate in cells and 'TLIN:' in net.read_text(encoding='utf-8', errors='ignore'):
            return candidate
    return None


def configure(user, workspace, p, enabled):
    cell = select_cell(workspace)
    if not cell:
        return None, None
    return capture.subscribe(user, workspace, cell, p, enabled), cell


def evidence(state):
    out = {}
    for i, stage in [(0,'baseline'), (2,'unmatched'), (3,'matched')]:
        if stage in state['stages']:
            item = state['stages'][stage]
            out[i] = f"仿真结果已验证：S11={item['s11_db']:.3f} dB，S21={item.get('s21_db',0):.3f} dB"
    if state['passed'][1]:
        out[1] = '短路、开路两次仿真已留存，幅度与相位符合理论'
    if state['bandwidth']:
        b = state['bandwidth']['bandwidth']
        out[4] = f"匹配频段 {b['low_ghz']:.5g}–{b['high_ghz']:.5g} GHz，带宽 {b['width_mhz']:.4g} MHz"
    return out


def values(state):
    out = {}
    stages = state['stages']
    if 'baseline' in stages:
        out['cp_tlin_setup'] = 1.
    if 'unmatched' in stages:
        out['cp_unmatched'] = stages['unmatched']['s11_db']
    if 'matched' in stages:
        out['cp_matched_s11'] = stages['matched']['s11_db']
        out['cp_s21'] = stages['matched']['s21_db']
    return out


@st.fragment(run_every='2s')
def monitor(key):
    state = capture.view(key)
    signature = (state['passed'], state['message'], state['alive'], [(r[0],r[2]) for r in state['records']])
    previous = st.session_state.get('lab2_monitor_signature')
    st.session_state['lab2_monitor_signature'] = signature
    if previous is not None and previous != signature:
        st.rerun(scope='app')
    st.caption('自动检测已开启：后台读取并验证 ADS 仿真结果' if state['alive'] else '后台采集未运行，请使用“启动实验陪练”入口启动。')
