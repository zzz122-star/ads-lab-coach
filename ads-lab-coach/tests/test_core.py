import math
import time

from coach import ads_watch, calc, checks, content, db

PARAMS = {"z0": 50.0, "er": 4.4, "h_mm": 1.6}


def test_width_roundtrip_gives_target_z0():
    w = calc.microstrip_width(50, 4.4, 1.6)
    assert abs(calc.microstrip_z0(w, 4.4, 1.6) - 50) < 1.0


def test_width_fr4_reasonable():
    assert 2.8 < calc.microstrip_width(50, 4.4, 1.6) < 3.3


def test_wide_and_narrow_branches():
    assert calc.microstrip_width(100, 4.4, 1.6) < calc.microstrip_width(50, 4.4, 1.6)
    assert calc.microstrip_width(30, 4.4, 1.6) > calc.microstrip_width(50, 4.4, 1.6)


def test_eeff_between_1_and_er():
    w = calc.microstrip_width(50, 4.4, 1.6)
    assert 1 < calc.microstrip_eeff(w, 4.4, 1.6) < 4.4


def test_range_check():
    cp = {"id": "a", "type": "range", "max": -10, "on_high": ["x"]}
    assert checks.evaluate(cp, {"a": -20.0}, PARAMS).status == "pass"
    r = checks.evaluate(cp, {"a": -5.0}, PARAMS)
    assert r.status == "fail" and r.hints == ["x"]
    assert checks.evaluate(cp, {}, PARAMS).status == "pending"


def test_match_calc():
    cp = {"id": "w", "type": "match_calc", "calc": "microstrip_width", "tolerance_pct": 5}
    w = calc.microstrip_width(50, 4.4, 1.6)
    assert checks.evaluate(cp, {"w": w * 1.02}, PARAMS).status == "pass"
    assert checks.evaluate(cp, {"w": w * 1.5}, PARAMS).status == "fail"


def test_passivity():
    cp = {"id": "p", "type": "passivity", "uses": ["s11", "s21"]}
    assert checks.evaluate(cp, {"s11": -20.0, "s21": -0.1}, PARAMS).status == "pass"
    assert checks.evaluate(cp, {"s11": -1.0, "s21": -1.0}, PARAMS).status == "fail"


def test_content_loads_and_references_resolve():
    exps = content.load_experiments()
    diag_ids = {d["id"] for d in content.load_diagnostics()}
    assert exps
    for e in exps:
        cp_ids = {c["id"] for c in e["checkpoints"]}
        for c in e["checkpoints"]:
            for u in c.get("uses", []):
                assert u in cp_ids
        for ce in e.get("common_errors", []):
            assert ce["diag_id"] in diag_ids


def test_diagnose_keyword():
    hits = content.diagnose("曲线全平没有数据", content.load_diagnostics())
    assert hits and hits[0]["id"] == "curve_empty"


def test_vswr_and_return_loss():
    assert abs(calc.vswr(100, 50) - 2.0) < 1e-9
    assert abs(calc.return_loss_db(100, 50) - 9.5424) < 0.01


def test_quarter_wave_len_reasonable():
    length = calc.quarter_wave_len(50, 4.4, 1.6, 2.4)
    assert 10 < length < 30


def _defaults(exp):
    return {p["key"]: p["default"] for p in exp["params"]}


def test_metrics_and_demo_complete():
    exps = content.load_experiments()
    assert len(exps) == 5
    for e in exps:
        params = _defaults(e)
        assert e.get("metrics"), e["id"]
        for m in e["metrics"]:
            value = calc.metric(m["calc"], params)
            assert math.isfinite(value), (e["id"], m["calc"])
        assert e.get("verification"), e["id"]
        assert e.get("demo", {}).get("pitch"), e["id"]
        assert e.get("demo", {}).get("qa"), e["id"]
        for s in e["steps"]:
            assert s.get("title") and s.get("action") and s.get("why"), (e["id"], s)


def test_step_progress_persists():
    conn = db.connect()
    db.save_step(conn, "u", "exp", 0, True)
    db.save_step(conn, "u", "exp", 1, False)
    assert db.load_steps(conn, "u", "exp") == {0: True, 1: False}
    assert db.step_counts(conn, "u") == {"exp": 1}


def test_detect_exp01_from_netlist(tmp_path):
    wrk = tmp_path / "demo_wrk"
    (wrk / "data").mkdir(parents=True)
    (wrk / "netlist.log").write_text(
        'Mlin:TL1 N__1 N__2 W=3 mm L=20 mm Subst="MSub1"\n'
        "model MSub1 MSUB H=1.6 mm Er=4.4 T=0.035 mm Tand=0.02\n"
        'S_Param:SP1 CalcS=yes SweepVar="freq" SweepPlan="SP1_stim"\n'
        "SweepPlan: SP1_stim Start=0.1 GHz Stop=5 GHz Step=.01 GHz\n"
        "Port:Term1 N__1 0 Num=1 Z=50 Ohm\n"
        "Port:Term2 N__2 0 Num=2 Z=50 Ohm\n",
        encoding="utf-8",
    )
    (wrk / "data" / "sim.ds").write_bytes(b"x")
    found = ads_watch.find_workspaces(tmp_path)
    assert found and found[0]["path"] == wrk
    assert set(ads_watch.detect_exp01(found[0])) == {0, 1, 2, 3, 4, 5}


def test_detect_exp01_only_workspace(tmp_path):
    wrk = tmp_path / "empty_wrk"
    cell = wrk / "demo_lib" / "cell"
    (cell / "schematic").mkdir(parents=True)
    (cell / "schematic" / "sch.oa").write_bytes(b"x")
    found = ads_watch.find_workspaces(tmp_path)
    assert found
    assert set(ads_watch.detect_exp01(found[0])) == {0}


def _write_ws(tmp_path, name, netlist, dds=True):
    wrk = tmp_path / name
    (wrk / "data").mkdir(parents=True)
    (wrk / "netlist.log").write_text(netlist, encoding="utf-8")
    if dds:
        (wrk / "data" / "sim.ds").write_bytes(b"x")
    return ads_watch.find_workspaces(tmp_path)[0]


def test_detect_exp02(tmp_path):
    ws = _write_ws(tmp_path, "tl_wrk", (
        "TLIN:TL1 N1 N2 Z=50 Ohm E=90 F=1 GHz\n"
        "TLIN:TL2 N2 N3 Z=70.7 Ohm E=90 F=1 GHz\n"
        "Port:Term1 N1 0 Num=1 Z=50 Ohm\n"
        "Port:Term2 N3 0 Num=2 Z=100 Ohm\n"
        "R:R1 N3 0 R=0 Ohm\n"
        'S_Param:SP1 CalcS=yes SweepVar="freq"\n'
        "SweepPlan: SP1_stim Start=0.1 GHz Stop=3 GHz Step=.01 GHz\n"
    ))
    assert set(ads_watch.detect("exp02_transmission_line", ws)) == {0, 2, 3}
    assert 1 not in ads_watch.detect("exp02_transmission_line", ws)


def test_detect_exp03(tmp_path):
    ws = _write_ws(tmp_path, "stub_wrk", (
        "Port:Term1 N1 0 Num=1 Z=100 Ohm\n"
        "TLIN:TL1 N1 N2 Z=50 Ohm E=45 F=2.4 GHz\n"
        "TLIN:TL2 N2 0 Z=50 Ohm E=60 F=2.4 GHz\n"
        "Mlin:TL3 N2 N3 W=3 mm L=10 mm Subst=\"MSub1\"\n"
        "MLOC:TL4 N3 0 W=1 mm L=8 mm Subst=\"MSub1\"\n"
        'S_Param:SP1 CalcS=yes SweepVar="freq"\n'
        "SweepPlan: SP1_stim Start=1 GHz Stop=4 GHz Step=.01 GHz\n"
    ))
    assert set(ads_watch.detect("exp03_single_stub", ws)) == {0, 1, 2, 3, 4}


def test_detect_exp04(tmp_path):
    ws = _write_ws(tmp_path, "lpf_wrk", (
        "model MSub1 MSUB H=1 mm Er=2.7 T=0.05 mm Tand=0.0003\n"
        + "".join(f'Mlin:TL{i} N{i} N{i+1} W=2 mm L=5 mm Subst="MSub1"\n' for i in range(5))
        + "".join(f"Mstep:S{i} N{i} N{i+1} W1=2 mm W2=0.4 mm\n" for i in range(4))
        + "Port:Term1 N0 0 Num=1 Z=50 Ohm\n"
        "Port:Term2 N5 0 Num=2 Z=50 Ohm\n"
        'S_Param:SP1 CalcS=yes SweepVar="freq"\n'
        "SweepPlan: SP1_stim Start=0.1 GHz Stop=10 GHz Step=.01 GHz\n"
    ))
    assert set(ads_watch.detect("exp04_stepped_lpf", ws)) == {1, 2, 3, 4}


def test_detect_exp05(tmp_path):
    ws = _write_ws(tmp_path, "wilkinson_wrk", (
        "Port:Term1 N1 0 Num=1 Z=50 Ohm\n"
        "Port:Term2 N2 0 Num=2 Z=50 Ohm\n"
        "Port:Term3 N3 0 Num=3 Z=50 Ohm\n"
        "TLIN:TL1 N1 N2 Z=70.7 Ohm E=90 F=2.4 GHz\n"
        "TLIN:TL2 N1 N3 Z=70.7 Ohm E=90 F=2.4 GHz\n"
        "R:R1 N2 N3 R=100 Ohm\n"
        "Mlin:TL3 N1 N4 W=1.7 mm L=17 mm Subst=\"MSub1\"\n"
        "Mlin:TL4 N1 N5 W=1.7 mm L=17 mm Subst=\"MSub1\"\n"
        'S_Param:SP1 CalcS=yes SweepVar="freq"\n'
        "SweepPlan: SP1_stim Start=1 GHz Stop=4 GHz Step=.01 GHz\n"
    ))
    assert set(ads_watch.detect("exp05_wilkinson", ws)) == {1, 2, 3, 4}


def test_detect_ignores_old_files(tmp_path):
    ws = _write_ws(tmp_path, "old_wrk", (
        'Mlin:TL1 N1 N2 W=3 mm L=20 mm Subst="MSub1"\n'
        "model MSub1 MSUB H=1.6 mm Er=4.4 T=0.035 mm Tand=0.02\n"
        "Port:Term1 N1 0 Num=1 Z=50 Ohm\n"
        "Port:Term2 N2 0 Num=2 Z=50 Ohm\n"
        'S_Param:SP1 CalcS=yes SweepVar="freq"\n'
        "SweepPlan: SP1_stim Start=0.1 GHz Stop=5 GHz Step=.01 GHz\n"
    ))
    assert ads_watch.detect("exp01_microstrip_sparam", ws, since=time.time() + 3600) == {}


def test_exp01_rejects_three_port_design(tmp_path):
    ws = _write_ws(tmp_path, "three_port_wrk", (
        'Mlin:TL1 N1 N2 W=3 mm L=20 mm Subst="MSub1"\n'
        "model MSub1 MSUB H=1.6 mm Er=4.4 T=0.035 mm Tand=0.02\n"
        "Port:Term1 N1 0 Num=1 Z=50 Ohm\n"
        "Port:Term2 N2 0 Num=2 Z=50 Ohm\n"
        "Port:Term3 N2 0 Num=3 Z=50 Ohm\n"
        'S_Param:SP1 CalcS=yes SweepVar="freq"\n'
    ))
    evidence = ads_watch.detect("exp01_microstrip_sparam", ws)
    assert 3 not in evidence


def test_exp03_rejects_plain_step_structure(tmp_path):
    ws = _write_ws(tmp_path, "step_wrk", (
        'Mlin:TL1 N1 N2 W=2 mm L=5 mm Subst="MSub1"\n'
        "Mstep:S1 N1 N2 W1=2 mm W2=0.4 mm\n"
        "Port:Term1 N1 0 Num=1 Z=50 Ohm\n"
        "Port:Term2 N2 0 Num=2 Z=50 Ohm\n"
        'S_Param:SP1 CalcS=yes SweepVar="freq"\n'
    ))
    evidence = ads_watch.detect("exp03_single_stub", ws)
    assert 3 not in evidence


def test_exp_start_is_stable():
    conn = db.connect()
    first = db.get_or_create_start(conn, "u", "exp")
    second = db.get_or_create_start(conn, "u", "exp")
    assert first == second


def test_set_detection_start_allows_rescan():
    conn = db.connect()
    db.set_detection_start(conn, "rescan", "exp", 0.0)
    assert db.get_or_create_start(conn, "rescan", "exp") == 0.0


def _write_schematic_ws(tmp_path, name="sch_wrk"):
    cell = tmp_path / name / f"{name}_lib" / "lab1"
    sch = cell / "schematic" / "sch.oa"
    sch.parent.mkdir(parents=True)
    sch.write_text(
        'TL1\nads_tlines.MLIN.symbol\nSubst="MSub1"\nW=25.0 mil\nW=3 mm\nL=100.0 mil\nL=20 mm\n'
        "MSub1\nads_tlines.MSUB.symbol\n"
        "H=10.0 um\nH=1.60 mm\nEr=9.6\nEr=4.4\nTanD=0\nTanD=0.02\nT=0.035 um\nT=0.035 mm\n"
        "Term1\nads_simulation.Term.symbol\nNum=1\nZ=50 Ohm\n"
        "Term2\nads_simulation.Term.symbol\nNum=2\nZ=50 Ohm\n"
        "SP1\nads_simulation.S_Param.symbol\n"
        "Start=1.0 GHz\nStop=10.0 GHz\nStep=1.0 GHz\n"
        "Start=0.1 GHz\nStop=5 GHz\nStep=0.01 GHz\n",
        encoding="utf-8",
    )
    (tmp_path / name / "data").mkdir()
    return ads_watch.find_workspaces(tmp_path)[0]


def test_parse_schematic_fields(tmp_path):
    ws = _write_schematic_ws(tmp_path)
    info = ws["schematic_info"]
    assert info["counts"]["MLIN"] == 1
    assert info["counts"]["MSUB"] == 1
    assert abs(info["params"]["W"] - 3.0) < 1e-9
    assert abs(info["params"]["Start"] - 0.1) < 1e-9
    assert {(t["num"], t["z"]) for t in info["terms"]} == {(1, 50.0), (2, 50.0)}


def test_scan_workspace_directory_itself(tmp_path):
    ws = _write_schematic_ws(tmp_path)
    found = ads_watch.find_workspaces(ws["path"])
    assert len(found) == 1
    assert found[0]["path"] == ws["path"]


def test_detect_exp01_from_schematic_without_netlist(tmp_path):
    ws = _write_schematic_ws(tmp_path)
    evidence = ads_watch.detect("exp01_microstrip_sparam", ws)
    assert {0, 1, 2, 3, 4}.issubset(evidence)
    assert 5 not in evidence

    (tmp_path / "sch_wrk" / "data" / "lab1.ds").write_bytes(b"x")
    ws = ads_watch.find_workspaces(tmp_path)[0]
    assert 5 in ads_watch.detect("exp01_microstrip_sparam", ws)


def test_exp03_short_stub_components(tmp_path):
    ws = _write_ws(tmp_path, "short_wrk", (
        "Port:Term1 N1 0 Num=1 Z=100 Ohm\n"
        "TLIN:TL1 N1 N2 Z=50 Ohm E=45 F=2.4 GHz\n"
        "TLSC:TL2 N2 Z=50 Ohm E=60 F=2.4 GHz\n"
        "Mlin:TL3 N2 N3 W=3 mm L=10 mm Subst=\"MSub1\"\n"
        "MLSC:TL4 N3 W=1 mm L=8 mm Subst=\"MSub1\"\n"
        'S_Param:SP1 CalcS=yes SweepVar="freq"\n'
        "SweepPlan: SP1_stim Start=1 GHz Stop=4 GHz Step=.01 GHz\n"
    ))
    assert set(ads_watch.detect("exp03_single_stub", ws)) == {0, 1, 2, 3, 4}


def test_stale_dataset_of_other_design_ignored(tmp_path):
    wrk = tmp_path / "multi_wrk"
    (wrk / "data").mkdir(parents=True)
    stale = wrk / "data" / "other.ds"
    stale.write_bytes(b"x")
    (wrk / "netlist.log").write_text(
        '; Top Design: "lib:mine:schematic"\n'
        "Port:Term1 N1 0 Num=1 Z=50 Ohm\n"
        "Port:Term2 N2 0 Num=2 Z=50 Ohm\n"
        'Mlin:TL1 N1 N2 W=3 mm L=20 mm Subst="MSub1"\n'
        "model MSub1 MSUB H=1.6 mm Er=4.4\n"
        'S_Param:SP1 CalcS=yes SweepVar="freq"\n',
        encoding="utf-8",
    )
    ws = ads_watch.find_workspaces(tmp_path)[0]
    assert 5 not in ads_watch.detect("exp01_microstrip_sparam", ws)
    (wrk / "data" / "mine.ds").write_bytes(b"x")
    ws = ads_watch.find_workspaces(tmp_path)[0]
    assert 5 in ads_watch.detect("exp01_microstrip_sparam", ws)


def test_dataset_older_than_netlist_ignored(tmp_path):
    import os
    wrk = tmp_path / "old_ds_wrk"
    (wrk / "data").mkdir(parents=True)
    ds = wrk / "data" / "mine.ds"
    ds.write_bytes(b"x")
    os.utime(ds, (time.time() - 600, time.time() - 600))
    (wrk / "netlist.log").write_text('; Top Design: "lib:mine:schematic"\n', encoding="utf-8")
    ws = ads_watch.find_workspaces(tmp_path)[0]
    assert ads_watch._fresh_ds(ws, 0.0) is None



def test_reset_experiment_clears_steps_and_moves_start():
    conn = db.connect()
    first = db.get_or_create_start(conn, "r", "exp")
    db.save_step(conn, "r", "exp", 0, True)
    db.reset_experiment(conn, "r", "exp")
    assert db.load_steps(conn, "r", "exp") == {}
    assert db.get_or_create_start(conn, "r", "exp") >= first
