"""Experiment 2: topology and numerical validation, independent of Streamlit."""
import cmath
import hashlib
import json
import math
import re

VERSION = 1
TITLES = ["双端口测试台", "短路与开路", "负载失配", "四分之一波长匹配", "扫频与匹配带宽"]
STAGES = ["baseline", "short", "open", "unmatched", "matched"]


def run_key(user, workspace, cell, params):
    payload = [VERSION, user, str(workspace), cell, sorted(params.items())]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=True).encode()).hexdigest()[:24]


def close(a, b, rel=0.01, absolute=1e-6):
    return abs(a - b) <= max(absolute, abs(b) * rel)


def parse_netlist(text):
    text = text.replace("\\\n", " ")
    lines, ports = [], []
    for raw in text.splitlines():
        match = re.match(r"\s*(TLIN|Port):([^\s]+)\s+(\S+)\s+(\S+)\s+(.*)", raw, re.I)
        if not match:
            continue
        kind, name, a, b, rest = match.groups()
        values = {}
        for key, value, unit in re.findall(r"\b(Z|E|F|Num)\s*=\s*([-+\d.eE]+)(?:\s*(GHz|MHz|kHz|Hz|Ohm)\b)?", rest):
            number = float(value)
            if key == "F":
                number *= {"GHz": 1, "MHz": .001, "kHz": 1e-6, "Hz": 1e-9}.get(unit, 1)
            values[key] = number
        item = dict(name=name, a=a, b=b, **values)
        (lines if kind.lower() == "tlin" else ports).append(item)
    devices = re.findall(r"^\s*([A-Za-z][\w]*):", text, re.M)
    unsupported = sorted(set(devices) - {"TLIN", "Port", "S_Param", "SweepPlan", "OutputPlan"})
    if unsupported:
        raise ValueError("本实验使用理想 TLIN 和 Term；检测到额外元件：" + ", ".join(unsupported))
    if not re.search(r"S_Param:", text, re.I):
        raise ValueError("缺少 S-Param 控制器")
    if not lines or len(lines) > 2:
        raise ValueError("应使用 1 段测试线，匹配阶段使用变换线及可选测试线（最多 2 段）")
    if len({p.get("Num") for p in ports}) != len(ports):
        raise ValueError("端口 Num 重复")
    return lines, ports


def topology(text, p):
    lines, ports = parse_netlist(text)
    input_ports = [port for port in ports if port.get("Num") == 1]
    if len(input_ports) != 1 or not close(input_ports[0].get("Z", -1), p["z0"]):
        raise ValueError(f"Term1 必须 Num=1、Z={p['z0']:g} Ω")
    port1 = input_ports[0]
    if port1["b"] != "0":
        raise ValueError("Term1 参考端必须接地")
    ordered, remaining = [], list(lines)
    node = port1["a"]
    while remaining:
        choices = [line for line in remaining if node in (line["a"], line["b"])]
        if len(choices) != 1:
            raise ValueError("TLIN 必须从端口 1 起串联连接，不能悬空、分支或形成环路")
        line = choices[0]
        ordered.append(line)
        remaining.remove(line)
        node = line["b"] if node == line["a"] else line["a"]
        if not close(line.get("F", -1), p["f0_ghz"], rel=.001):
            raise ValueError(f"{line['name']} 的 F 应为 {p['f0_ghz']:g} GHz")
        if not close(line.get("E", -1), 90, rel=.001):
            raise ValueError(f"{line['name']} 的 E 应为 90°")
        if line.get("Z", 0) <= 0:
            raise ValueError("传输线阻抗必须大于 0")
    if len(ports) == 1:
        if len(ordered) != 1 or not close(ordered[0]["Z"], p["z0"]):
            raise ValueError("开路/短路使用单段 Z=系统阻抗、E=90° 的 TLIN")
        return ("short" if node == "0" else "open"), ordered
    if len(ports) != 2:
        raise ValueError("双端口阶段需要两个 Term；开路/短路阶段请删除 Term2")
    port2 = next((port for port in ports if port.get("Num") == 2), None)
    if not port2 or port2["a"] != node or port2["b"] != "0" or node == "0":
        raise ValueError("Term2 必须 Num=2、接在传输线末端，参考端接地")
    zt = math.sqrt(p["z0"] * p["zl"])
    if len(ordered) == 1 and close(ordered[0]["Z"], p["z0"]):
        if close(port2.get("Z", -1), p["z0"]):
            return "baseline", ordered
        if close(port2.get("Z", -1), p["zl"]):
            return "unmatched", ordered
    if close(port2.get("Z", -1), p["zl"]):
        expected = [zt] if len(ordered) == 1 else [p["z0"], zt]
        if all(close(line["Z"], z) for line, z in zip(ordered, expected)):
            return "matched", ordered
    raise ValueError(f"电路与本轮参数不一致：测试线 {p['z0']:g} Ω，负载 Term2={p['zl']:g} Ω，变换线 {zt:.3f} Ω")


def theory(stage, lines, frequencies, p):
    out11, out21 = [], []
    for frequency in frequencies:
        a, b, c, d = 1+0j, 0j, 0j, 1+0j
        for line in lines:
            angle = math.radians(line["E"]) * frequency / (line["F"] * 1e9)
            x, y = math.cos(angle), 1j * math.sin(angle)
            z = line["Z"]
            a, b, c, d = a*x+b*y/z, a*y*z+b*x, c*x+d*y/z, c*y*z+d*x
        z1 = p["z0"]
        if stage in ("short", "open"):
            numerator, denominator = (b-z1*d, b+z1*d) if stage == "short" else (a-z1*c, a+z1*c)
            out11.append(numerator / denominator)
        else:
            z2 = p["z0"] if stage == "baseline" else p["zl"]
            denominator = a*z2+b+z1*(c*z2+d)
            out11.append((a*z2+b-z1*(c*z2+d)) / denominator)
            out21.append(2 * math.sqrt(z1*z2) / denominator)
    return out11, out21


def db20(value):
    return 20 * math.log10(max(abs(value), 1e-15))


def bandwidth(freqs, s11, f0, threshold=-20):
    center = min(range(len(freqs)), key=lambda i: abs(freqs[i]-f0))
    values = [db20(v) for v in s11]
    if values[center] >= threshold:
        return None
    left = right = center
    while left > 0 and values[left-1] < threshold:
        left -= 1
    while right < len(freqs)-1 and values[right+1] < threshold:
        right += 1
    if left == 0 or right == len(freqs)-1:
        return None
    def crossing(i, j):
        return freqs[i] + (freqs[j]-freqs[i]) * (threshold-values[i]) / (values[j]-values[i])
    lo, hi = crossing(left-1, left), crossing(right, right+1)
    return {"low_ghz": lo/1e9, "high_ghz": hi/1e9, "width_mhz": (hi-lo)/1e6}


def validate(text, data, p):
    if close(p["z0"], p["zl"], rel=.02):
        raise ValueError("负载和系统阻抗过于接近，无法观察失配及有限的匹配带宽；请设置不同阻抗")
    stage, lines = topology(text, p)
    freqs = data["freq"]
    if len(freqs) < 3 or not all(math.isfinite(f) and f > 0 for f in freqs):
        raise ValueError("仿真需要至少三个有效正频率点")
    if any(a >= b for a, b in zip(freqs, freqs[1:])):
        raise ValueError("仿真频率必须严格递增")
    variables = {k: [complex(*v) for v in values] for k, values in data["variables"].items()}
    if any(len(v) != len(freqs) or any(not math.isfinite(x.real) or not math.isfinite(x.imag) for x in v) for v in variables.values()):
        raise ValueError("数据长度不一致或包含无效数值")
    f0 = p["f0_ghz"] * 1e9
    center = min(range(len(freqs)), key=lambda i: abs(freqs[i]-f0))
    if abs(freqs[center]-f0) > f0*1e-5:
        raise ValueError(f"扫频需包含中心频率 {p['f0_ghz']:g} GHz，请调整 Start/Step")
    for port, target in [(1, p["z0"])] + ([] if stage in ("short", "open") else [(2, p["z0"] if stage == "baseline" else p["zl"])]):
        vals = variables.get(f"PortZ[{port}]")
        if not vals or any(not close(v, target) for v in vals):
            raise ValueError(f"数据集端口 {port} 的参考阻抗与网表/网页不一致；应为 {target:g} Ω，请重新仿真")
    expected11, expected21 = theory(stage, lines, freqs, p)
    for name, expected in [("S[1,1]", expected11)] + ([("S[2,1]", expected21)] if expected21 else []):
        actual = variables.get(name)
        if actual is None:
            raise ValueError(f"结果缺少 {name}，请确认端口编号并重新仿真")
        error = max(abs(a-b) for a, b in zip(actual, expected))
        if error > .02:
            raise ValueError(f"{name} 与该电路理论复数值不符，最大偏差 {error:.4f} > 0.02；核对连线、阻抗和数据集是否属于本次仿真")
    s11 = variables["S[1,1]"]
    summary = {"stage": stage, "s11_db": db20(s11[center]), "phase_deg": math.degrees(cmath.phase(s11[center])), "max_complex_error": max(abs(a-b) for a,b in zip(s11, expected11))}
    if expected21:
        summary["s21_db"] = db20(variables["S[2,1]"][center])
    if stage == "matched" and summary["s11_db"] > -20:
        raise ValueError("中心频率 S11 未低于 -20 dB，请核对变换线阻抗与电长度")
    summary["bandwidth"] = bandwidth(freqs, s11, f0) if stage == "matched" else None
    wide = freqs[0] <= .1001*f0 and freqs[-1] >= 2.999*f0 and max(b-a for a,b in zip(freqs,freqs[1:])) <= .0101*f0
    summary["full_sweep"] = wide
    summary["bandwidth_pass"] = stage == "matched" and wide and summary["bandwidth"] is not None
    return summary
