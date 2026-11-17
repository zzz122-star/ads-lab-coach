import time
from pathlib import Path

import streamlit as st

from coach import ads_watch, calc, checks, content, db, lab2_ui, capture

st.set_page_config(page_title="ADS 实验陪练", layout="wide")

STATUS_ICON = {"pass": "通过", "fail": "未通过", "pending": "待填写"}


@st.cache_resource
def get_conn():
    return db.connect()


@st.cache_data
def get_content():
    return content.load_experiments(), content.load_diagnostics(), content.load_cards()


conn = get_conn()
experiments, diagnostics, cards = get_content()

user = st.sidebar.text_input("你的姓名", key="user").strip()
ads_root = st.sidebar.text_input("ADS 工程目录", value=str(Path.home() / "Documents" / "ADS"))
auto_detect = st.sidebar.checkbox("自动检测 ADS 完成状态", value=True)
page = st.sidebar.radio("页面", ["实验向导", "故障诊断", "知识卡片", "小组进度"])

if not user and page != "知识卡片":
    st.info("请先在左侧输入姓名，进度会按姓名保存。")
    st.stop()


@st.fragment(run_every="1s")
def watch_ads(exp_id, ads_root, selected_path, since):
    # Fragment reruns do not rerun render_experiment: refresh the file snapshot here.
    workspaces = ads_watch.find_workspaces(Path(ads_root))
    ws = next((w for w in workspaces if w["path"] == selected_path), None)
    evidence = ads_watch.detect(exp_id, ws, since) if ws else {}
    signature = (tuple(str(w["path"]) for w in workspaces), tuple(sorted(evidence.items())))
    key = f"{exp_id}_ads_sig"
    previous = st.session_state.get(key)
    st.session_state[key] = signature
    if previous is not None and previous != signature:
        st.rerun(scope="app")
    st.caption("自动检测已开启：每秒检查一次 ADS 文件")


def render_steps(exp, exp_id, ws, since, lab_state=None, run_id=None):
    manual = db.load_steps(conn, user, exp_id)
    auto = lab2_ui.evidence(lab_state) if lab_state else (ads_watch.detect(exp_id, ws, since) if ws and exp_id != "exp02_transmission_line" else {})
    if exp_id == "exp02_transmission_line":
        manual = db.load_steps(conn, user, run_id) if run_id else {}

    total = len(exp["steps"])
    for i in auto:
        if not manual.get(i):
            db.save_step(conn, user, run_id or exp_id, i, True)
            manual[i] = True
    done_flags = [bool(manual.get(i)) or i in auto for i in range(total)]
    done_count = sum(done_flags)
    st.progress(done_count / total, text=f"已完成 {done_count}/{total} 步")

    for i, s in enumerate(exp["steps"]):
        is_auto = i in auto
        suffix = " ⚡ 自动检测" if is_auto else (" ✅ 已完成" if done_flags[i] else "")
        content_status = "已验证" if s.get("verified") else ("文档已核对" if s.get("doc_verified") else "未验证")
        with st.expander(f"{i + 1}. {s['title']}{suffix}", expanded=not done_flags[i]):
            st.write(s["action"])
            if s.get("key_params"):
                st.markdown(f"**关键参数**：{s['key_params']}")
            st.markdown(f"**为什么**：{s['why']}")
            if s.get("ui_path"):
                st.caption(f"路径：{s['ui_path']}")
                if s.get("doc_ref"):
                    st.caption(f"依据：{s['doc_ref']}")
            else:
                st.caption("菜单路径待实操后补充。")
            st.caption(f"内容核对状态：{content_status}（与你的完成进度分开记录）")
            st.caption(f"自动检测：{auto[i]}" if is_auto else "自动检测：未识别到证据")
            if lab_state and i == 1 and not is_auto:
                for stage, name in [("short", "短路"), ("open", "开路")]:
                    item = lab_state["stages"].get(stage)
                    st.caption(f"{name}已留存，相位 {item['phase_deg']:.2f}°" if item else f"等待{name}仿真结果")
            widget_key = f"{run_id or exp_id}_step_{i}"
            if is_auto:
                st.session_state[widget_key] = True
            checked = st.checkbox(
                "我已完成这一步", value=done_flags[i], disabled=is_auto, key=widget_key
            )
            if not is_auto and checked != bool(manual.get(i)):
                db.save_step(conn, user, run_id or exp_id, i, checked)
    if done_count == total:
        st.success("步骤已全部完成，可以继续填写下面的检查点。")


def render_experiment():
    counts = db.step_counts(conn, user)

    def label(e):
        return f"{e['title']}（{counts.get(e['id'], 0)}/{len(e['steps'])} 步）"

    exp = st.selectbox("选择实验", experiments, format_func=label)
    exp_id = exp["id"]
    st.caption(f"预计 {exp['estimated_minutes']} 分钟")
    st.subheader("目标")
    st.write(exp["goal"])

    saved_params = db.load_params(conn, user, exp_id)
    st.subheader("参数")
    param_defs = exp["params"]
    params = {}
    for start in range(0, len(param_defs), 3):
        cols = st.columns(3)
        for col, p in zip(cols, param_defs[start:start + 3]):
            label = f"{p['label']} ({p['unit']})" if p["unit"] else p["label"]
            lo, hi = p.get("min"), p.get("max")
            default = float(saved_params.get(p["key"], p["default"]))
            if lo is not None:
                default = max(default, lo)
            if hi is not None:
                default = min(default, hi)
            value = col.number_input(
                label,
                value=default,
                min_value=float(lo) if lo is not None else None,
                max_value=float(hi) if hi is not None else None,
                step=float(p.get("step", 1.0)),
                key=f"{exp_id}_{p['key']}",
            )
            params[p["key"]] = value
            if saved_params.get(p["key"]) != value:
                db.save_param(conn, user, exp_id, p["key"], value)

    if exp_id == "exp02_transmission_line":
        exp = lab2_ui.prepare(exp, params)

    metrics = exp.get("metrics") or []
    for start in range(0, len(metrics), 4):
        cols = st.columns(4)
        for col, m in zip(cols, metrics[start:start + 4]):
            value = calc.metric(m["calc"], params) if not (m["calc"] == "return_loss_db" and params.get("zl") == params.get("z0")) else float("inf")
            unit = m.get("unit", "")
            digits = int(m.get("digits", 2))
            text = f"{value:.{digits}f}"
            col.metric(m["label"], f"{text} {unit}".strip())

    lab_key = None
    lab_state = None
    lab_workspace = None
    lab_cell = None
    if exp_id == "exp02_transmission_line":
        workspaces = ads_watch.find_workspaces(Path(ads_root))
        if workspaces:
            workspaces.sort(key=lambda w: lab2_ui.select_cell(w["path"]) != "lab2")
            selected_path = st.session_state.get(f"{exp_id}_ws_path", workspaces[0]["path"])
            lab_workspace = next((w for w in workspaces if w["path"] == selected_path), workspaces[0])
            lab_key, lab_cell = lab2_ui.configure(user, lab_workspace["path"], params, auto_detect)
            if lab_key:
                lab_state = capture.view(lab_key)
    st.subheader("操作步骤")
    with st.expander("重新开始本实验"):
        st.caption(
            "「重新开始」清空步骤进度，并且只统计此刻之后生成的文件。"
            "「按现有文件重新检测」不清空步骤，但会忽略时间起点，把当前已保存的原理图和仿真数据也算进来。"
        )
        c1, c2 = st.columns(2)
        if c1.button("重新开始", key=f"{exp_id}_reset"):
            if lab_key:
                capture.reset(lab_key)
                conn.execute("DELETE FROM steps WHERE user=? AND exp_id=?", (user, lab_key))
                conn.commit()
            db.reset_experiment(conn, user, exp_id)
            for k in [k for k in st.session_state if k.startswith((f"{exp_id}_step_", f"{exp_id}_auto_step_"))]:
                del st.session_state[k]
            st.rerun()
        if c2.button("按现有文件重新检测", key=f"{exp_id}_rescan"):
            if lab_key:
                with capture.connect() as c:
                    c.execute("UPDATE lab2_runs SET since=0 WHERE id=?", (lab_key,))
            db.set_detection_start(conn, user, exp_id, 0.0)
            st.rerun()
    start_ts = db.get_or_create_start(conn, user, exp_id)
    ws = None
    if auto_detect:
        workspaces = ads_watch.find_workspaces(Path(ads_root))
        if exp_id == "exp02_transmission_line":
            workspaces.sort(key=lambda w: lab2_ui.select_cell(w["path"]) != "lab2")
        if workspaces:
            labels = [ads_watch.workspace_label(w) for w in workspaces]
            selected = st.selectbox(
                "ADS 工作区（自动检测）",
                [w["path"] for w in workspaces],
                format_func=lambda path: labels[next(i for i,w in enumerate(workspaces) if w["path"] == path)],
                key=f"{exp_id}_ws",
            )
            ws = next(w for w in workspaces if w["path"] == selected)
            if exp_id == "exp02_transmission_line" and lab_workspace and selected != lab_workspace["path"]:
                st.session_state[f"{exp_id}_ws_path"] = selected
                st.rerun()
            st.caption(
                f"当前设计：{(lab_cell or '未找到 lab2') if exp_id == 'exp02_transmission_line' else ws.get('design') or '未保存'}"
                "，只统计开始本实验之后生成的文件"
            )
            st.caption(f"正在检测：{ws['path']}（请确认这是 lab2 所在的工程，并在 ADS 中保存原理图）")
        else:
            st.caption(f"未在 {ads_root} 下找到 ADS 工作区，先用手动勾选。")
        if exp_id == "exp02_transmission_line":
            if lab_key:
                lab2_ui.monitor(lab_key)
                st.caption(lab_state["message"])
            else:
                st.caption("未识别实验 2 设计，请将原理图命名为 lab2 并保存。")
        else:
            watch_ads(exp_id, ads_root, ws["path"] if ws else None, start_ts)
    render_steps(exp, exp_id, ws, start_ts, lab_state, lab_key)

    st.subheader("预期结果")
    st.write(exp["expected"])

    demo = exp.get("demo")
    if demo:
        st.subheader("演示讲稿")
        for point in demo.get("pitch", []):
            st.markdown(f"- {point}")
        for qa in demo.get("qa", []):
            with st.expander(f"Q：{qa['q']}"):
                st.write(qa["a"])

    st.subheader("检查点（结果自动判定）")
    values = db.load_values(conn, user, lab_key or exp_id)
    if lab_key and st.session_state.get("lab2_value_run") != lab_key:
        for cp in exp["checkpoints"]:
            st.session_state.pop(f"{exp_id}_{cp['id']}", None)
        st.session_state["lab2_value_run"] = lab_key
    if lab_state:
        for cid, value in lab2_ui.values(lab_state).items():
            values[cid] = value
            st.session_state[f"{exp_id}_{cid}"] = ("是" if value else "否") if cid == "cp_tlin_setup" else f"{value:g}"
    for cp in exp["checkpoints"]:
        kind = cp["type"]
        if kind == "passivity":
            continue
        key = f"{exp_id}_{cp['id']}"
        if kind == "confirm":
            choice = st.radio(
                cp["title"], ["未填写", "是", "否"], horizontal=True, key=key,
                index={1.0: 1, 0.0: 2}.get(values.get(cp["id"]), 0),
            )
            if choice != "未填写":
                values[cp["id"]] = 1.0 if choice == "是" else 0.0
                db.save_value(conn, user, lab_key or exp_id, cp["id"], values[cp["id"]])
        else:
            label = f"{cp['title']} ({cp.get('unit', '')})"
            default = values.get(cp["id"])
            txt = st.text_input(label, value="" if default is None else f"{default:g}", key=key)
            if txt.strip():
                try:
                    values[cp["id"]] = float(txt)
                    db.save_value(conn, user, lab_key or exp_id, cp["id"], values[cp["id"]])
                except ValueError:
                    st.error("请输入数字")

    cp_types = {c["id"]: c["type"] for c in exp["checkpoints"]}
    results = checks.evaluate_all(
        exp["checkpoints"],
        {k: (bool(v) if cp_types[k] == "confirm" else v) for k, v in values.items()},
        params,
    )
    manual = [r for cid, r in results.items() if cp_types[cid] != "passivity"]
    passed = sum(r.status == "pass" for r in manual)
    st.progress(passed / len(manual), text=f"已通过 {passed}/{len(manual)}")
    for cp in exp["checkpoints"]:
        r = results[cp["id"]]
        title = cp["title"] + ("（自动计算）" if cp["type"] == "passivity" else "")
        line = f"**{title}**：{STATUS_ICON[r.status]} {r.message}"
        if r.status == "pass":
            st.success(line)
        elif r.status == "fail":
            st.error(line)
            for h in r.hints:
                st.markdown(f"- {h}")
        else:
            st.markdown(f"- {line}")

    with st.expander("常见错误"):
        by_id = {d["id"]: d for d in diagnostics}
        for e in exp.get("common_errors", []):
            st.markdown(f"**{e['symptom']}**")
            for c in by_id[e["diag_id"]]["causes"]:
                st.markdown(f"- {c['cause']}（{c['check']}）")


def render_diagnose():
    q = st.text_input("描述你遇到的现象")
    if q:
        hits = content.diagnose(q, diagnostics)
        if not hits:
            st.warning("库里没有匹配条目，可在下方提交，补充进诊断库。")
        for d in hits:
            st.subheader(d["symptom"])
            if not d.get("verified"):
                st.caption("该条目尚未经实操验证。")
            for i, c in enumerate(d["causes"], 1):
                st.markdown(f"{i}. **{c['cause']}** —— {c['check']}")
    with st.expander("提交新问题 / 补充原因"):
        symptom = st.text_input("现象", key="rep_symptom")
        cause = st.text_area("你找到的原因或解决方法（可选）", key="rep_cause")
        if st.button("提交") and symptom.strip():
            db.add_report(conn, user, None, symptom.strip(), cause.strip())
            st.success("已记录")


def render_cards():
    name = st.selectbox("知识卡片", list(cards))
    st.markdown(cards[name])


def render_group():
    st.subheader("每人进度")
    rows = db.progress_overview(conn)
    totals = {e["id"]: len(e["steps"]) for e in experiments}
    counts_by_user = {}
    table = []
    for u, e, n, t in rows:
        if u not in counts_by_user:
            counts_by_user[u] = db.step_counts(conn, u)
        table.append({
            "姓名": u,
            "实验": e,
            "已完成步骤": f"{counts_by_user[u].get(e, 0)}/{totals.get(e, '?')}",
            "已填检查点": n,
            "最近更新": time.strftime("%m-%d %H:%M", time.localtime(t)),
        })
    st.table(table)
    st.subheader("大家提交的问题")
    st.table(
        [{"姓名": u, "现象": s, "原因/解决": c or "", "时间": time.strftime("%m-%d %H:%M", time.localtime(t))}
         for u, _, s, c, t in db.list_reports(conn)]
    )


{"实验向导": render_experiment, "故障诊断": render_diagnose, "知识卡片": render_cards, "小组进度": render_group}[page]()
