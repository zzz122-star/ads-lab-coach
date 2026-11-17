import cmath
import json
import math
from pathlib import Path

import pytest

from coach import capture, lab2

PARAMS = {"z0": 50., "zl": 100., "f0_ghz": 1., "er": 4.4, "h_mm": 1.6}


def fixture(stage, p=None):
    p = p or PARAMS
    z, load, f0 = p["z0"], p["zl"], p["f0_ghz"]
    net = '; Top Design: "test_lib:lab2:schematic"\n'
    end = "0" if stage == "short" else "far"
    net += f'TLIN:TL1 input {end if stage != "matched" else "middle"} Z={z} Ohm E=90 F={f0} GHz\n'
    if stage == "matched":
        net += f'TLIN:TL2 middle far Z={math.sqrt(z*load)} Ohm E=90 F={f0} GHz\n'
    net += f'Port:Term1 input 0 Num=1 Z={z} Ohm\n'
    z2 = z if stage == "baseline" else load
    if stage not in ("short", "open"):
        net += f'Port:Term2 far 0 Num=2 Z={z2} Ohm\n'
    net += 'S_Param:SP1 CalcS=yes SweepVar="freq"\n'
    frequencies = [f0*1e9*i/100 for i in range(10,301)]
    s11, s21 = [], []
    # Independent reflection / input-impedance equations, not the ABCD validator.
    for freq in frequencies:
        theta = math.pi/2 * freq/(f0*1e9)
        rotation = cmath.exp(-2j*theta)
        if stage in ("short", "open"):
            s11.append(rotation * (-1 if stage == "short" else 1))
        elif stage != "matched":
            gamma = (z2-z)/(z2+z)
            s11.append(gamma*rotation)
            s21.append(math.sqrt(1-gamma**2)*cmath.exp(-1j*theta))
        else:
            zt = math.sqrt(z*load)
            tan = math.tan(theta)
            zin = zt * (load+1j*zt*tan)/(zt+1j*load*tan)
            gamma = (zin-z)/(zin+z)
            s11.append(gamma*rotation)
            # Product of matched through-line delay and quarter-wave two-port transfer.
            transfer = 2*math.sqrt(z*load)/((load+z)*math.cos(theta)+1j*(zt+z*load/zt)*math.sin(theta))
            s21.append(transfer*cmath.exp(-1j*theta))
    def pairs(values):
        return [[v.real,v.imag] for v in values]
    variables = {"S[1,1]": pairs(s11), "PortZ[1]": pairs([complex(z)]*len(frequencies))}
    if s21:
        variables.update({"S[2,1]":pairs(s21), "PortZ[2]":pairs([complex(z2)]*len(frequencies))})
    return net, {"freq":frequencies,"variables":variables}


@pytest.mark.parametrize("stage", lab2.STAGES)
def test_all_states_against_independent_theory(stage):
    text,data=fixture(stage)
    result=lab2.validate(text,data,PARAMS)
    assert result["stage"] == stage
    if stage == "matched":
        assert result["bandwidth_pass"]
        assert 300 < result["bandwidth"]["width_mhz"] < 400


def test_parameter_changes_and_wrong_results():
    p=dict(PARAMS,z0=75.,zl=150.,f0_ghz=2.)
    text,data=fixture("matched",p)
    assert lab2.validate(text,data,p)["bandwidth_pass"]
    with pytest.raises(ValueError, match="Term1"):
        lab2.validate(text,data,PARAMS)
    data["variables"]["S[1,1]"][0]=[.8,.8]
    with pytest.raises(ValueError, match="偏差"):
        lab2.validate(text,data,p)
    assert lab2.run_key("a","wrk","lab2",p) != lab2.run_key("a","wrk","lab2",PARAMS)


def test_wrong_topology_and_missing_bandwidth():
    text,data=fixture("matched")
    with pytest.raises(ValueError, match="串联"):
        lab2.validate(text.replace("TLIN:TL2 middle far", "TLIN:TL2 disconnected far"),data,PARAMS)
    text,data=fixture("matched")
    data={"freq":data["freq"][80:101],"variables":{k:v[80:101] for k,v in data["variables"].items()}}
    result=lab2.validate(text,data,PARAMS)
    assert not result["bandwidth_pass"]


def test_history_capture_without_browser(tmp_path,monkeypatch):
    monkeypatch.setattr(capture.db,"DB_PATH",tmp_path/"test.db")
    monkeypatch.setattr(capture,"ARCHIVE",tmp_path/"evidence")
    workspace=tmp_path/"test_wrk"
    (workspace/"data").mkdir(parents=True)
    key=capture.subscribe("tester",workspace,"lab2",PARAMS)
    collector=capture.Collector()
    payload={}
    monkeypatch.setattr(capture,"read_dataset",lambda path: payload["data"])
    for stage in lab2.STAGES:
        text,data=fixture(stage)
        payload["data"]=data
        (workspace/"netlist.log").write_text(text)
        (workspace/"data"/"lab2.ds").write_text(stage)
        collector.tick() # settle
        collector.tick() # acquire
    state=capture.view(key)
    assert state["passed"] == [True]*5
    assert len(state["records"]) == 5
    assert all(Path(row[3],"result.ds").exists() for row in state["records"])
    p=dict(PARAMS,f0_ghz=2.)
    new=capture.subscribe("tester",workspace,"lab2",p)
    assert capture.view(new)["passed"] == [False]*5
    assert capture.view(key)["passed"] == [True]*5
    capture.reset(key)
    assert not any(capture.view(key)["passed"])


def test_saved_schematic_is_not_simulation_evidence(tmp_path,monkeypatch):
    monkeypatch.setattr(capture.db,"DB_PATH",tmp_path/"test.db")
    workspace=tmp_path/"test_wrk"
    sch=workspace/"test_lib"/"lab2"/"schematic"/"sch.oa"
    sch.parent.mkdir(parents=True)
    sch.write_bytes(b'saved schematic')
    key=capture.subscribe('tester',workspace,'lab2',PARAMS)
    collector=capture.Collector()
    collector.tick()
    assert not any(capture.view(key)["passed"])
    assert '缺少' in capture.view(key)["message"]


def test_lab2_design_is_not_alphabetically_first(tmp_path):
    from coach import lab2_ui
    for cell in ['%D%C_%N%O%M%S', 'lab1', 'lab2']:
        sch=tmp_path/'lib'/cell/'schematic'/'sch.oa'
        sch.parent.mkdir(parents=True)
        sch.write_bytes(b'')
    assert lab2_ui.select_cell(tmp_path) == 'lab2'
