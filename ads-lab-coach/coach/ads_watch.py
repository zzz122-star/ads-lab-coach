import re
import time
from collections import Counter
from pathlib import Path

TOP_DESIGN_RE = re.compile(r';\s*Top Design:\s*"([^"]+)"', re.IGNORECASE)
SYMBOL_RE = re.compile(r"^ads_[A-Za-z0-9_]+\.([A-Za-z0-9_]+)\.symbol$")
ASSIGN_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=([-\d.eE+]+)\s*([A-Za-z%]*)$")

_PARSE_CACHE = {}
_PARSE_CACHE_LIMIT = 64

_LEN_TO_MM = {"mm": 1.0, "mil": 0.0254, "um": 0.001, "cm": 10.0, "m": 1000.0, "": 1.0}
_FREQ_TO_GHZ = {"GHz": 1.0, "MHz": 1e-3, "kHz": 1e-6, "Hz": 1e-9, "": 1.0}


def find_workspaces(root: Path) -> list:
    """扫描 ADS 工程目录，返回按最近修改排序的工作区。"""
    if not root.exists():
        return []
    found = []
    candidates = list(root.rglob("*_wrk"))
    if root.is_dir() and root.name.endswith("_wrk"):
        candidates.insert(0, root)
    for wrk in candidates:
        if not wrk.is_dir():
            continue
        netlists = [p for p in wrk.rglob("netlist.log") if p.is_file()]
        schematics = [p for p in wrk.rglob("sch.oa") if p.is_file()]
        if not netlists and not schematics:
            continue
        newest_netlist = max(netlists, key=lambda p: p.stat().st_mtime) if netlists else None
        newest_schematic = max(schematics, key=lambda p: p.stat().st_mtime) if schematics else None
        stamps = [p.stat().st_mtime for p in netlists + schematics]
        found.append({
            "path": wrk,
            "mtime": max(stamps),
            "netlist": newest_netlist,
            "netlist_mtime": newest_netlist.stat().st_mtime if newest_netlist else 0.0,
            "top_design": _top_design(newest_netlist),
            "schematic": newest_schematic,
            "schematic_mtime": newest_schematic.stat().st_mtime if newest_schematic else 0.0,
            "schematic_cell": newest_schematic.parent.parent.name if newest_schematic else "",
            "schematic_info": _cached_parse(newest_schematic) if newest_schematic else None,
            "design": (
                newest_schematic.parent.parent.name
                if newest_schematic and newest_schematic.stat().st_mtime >= (
                    newest_netlist.stat().st_mtime if newest_netlist else 0.0
                )
                else (_top_design(newest_netlist) or (newest_schematic.parent.parent.name if newest_schematic else ""))
            ),
            "datasets": [(p, p.stat().st_mtime) for p in (wrk / "data").glob("*.ds") if p.is_file()],
        })
    found.sort(key=lambda w: w["mtime"], reverse=True)
    return found


def _read(path):
    if path is None:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _top_design(path) -> str:
    match = TOP_DESIGN_RE.search(_read(path))
    return match.group(1) if match else ""


def _cached_parse(path: Path) -> dict:
    try:
        stat = path.stat()
    except OSError:
        return {"instances": [], "counts": Counter(), "terms": [], "params": {}, "grounds": 0}
    key = (str(path), stat.st_mtime, stat.st_size)
    if key not in _PARSE_CACHE:
        if len(_PARSE_CACHE) > _PARSE_CACHE_LIMIT:
            _PARSE_CACHE.clear()
        _PARSE_CACHE[key] = parse_schematic(path)
    return _PARSE_CACHE[key]


def _convert(key: str, value: float, unit: str):
    if key in ("W", "L", "H", "T", "Hu", "Rough", "Wall1", "Wall2"):
        return value * _LEN_TO_MM.get(unit, 1.0)
    if key in ("Start", "Stop", "Step", "Center", "Span"):
        return value * _FREQ_TO_GHZ.get(unit, 1.0)
    return value


def parse_schematic(path: Path) -> dict:
    """解析 ADS OpenAccess 原理图里可读的字符串字段。

    基于 2027 实际保存文件：元件块以「实例名 + ads_*.symbol」出现，
    实际参数值在文件末尾的显示缓存中，因此同名参数取最后一次出现。
    """
    data = path.read_bytes()
    strings = [(m.start(), m.group().decode("latin1")) for m in re.finditer(rb"[ -~]{2,}", data)]

    instances = []
    term_names = []
    for idx, (offset, text) in enumerate(strings):
        if re.fullmatch(r"Term\d+", text):
            term_names.append((offset, text))
            continue
        symbol = SYMBOL_RE.match(text)
        if symbol and idx > 0:
            if symbol.group(1) == "Term":
                continue
            instances.append({
                "name": strings[idx - 1][1],
                "type": symbol.group(1),
                "offset": offset,
            })
    for offset, name in term_names:
        instances.append({"name": name, "type": "Term", "offset": offset})
    instances.sort(key=lambda inst: inst["offset"])

    params = {}
    params_all = {}
    for _, text in strings:
        match = ASSIGN_RE.match(text)
        if not match:
            continue
        key, raw, unit = match.groups()
        value = _convert(key, float(raw), unit)
        params[key] = value
        params_all.setdefault(key, []).append(value)

    terms = []
    last_z = None
    for i, inst in enumerate(instances):
        if inst["type"] != "Term":
            continue
        end = instances[i + 1]["offset"] if i + 1 < len(instances) else len(data)
        block = [s for off, s in strings if inst["offset"] <= off < end]
        num = z = None
        for text in block:
            match = ASSIGN_RE.match(text)
            if not match:
                continue
            key, raw, unit = match.groups()
            if key == "Num":
                num = int(float(raw))
            elif key == "Z":
                z = float(raw)
        if z is None:
            z = last_z
        else:
            last_z = z
        terms.append({"name": inst["name"], "num": num, "z": z})

    counts = Counter(inst["type"] for inst in instances)
    return {
        "path": str(path),
        "mtime": path.stat().st_mtime,
        "instances": instances,
        "counts": counts,
        "terms": terms,
        "params": params,
        "params_all": params_all,
        "grounds": counts.get("GROUND", 0),
    }


def _count(text: str, name: str) -> int:
    return len(re.findall(rf"\b{name}\s*:", text, re.IGNORECASE))


def _param(line: str, key: str):
    match = re.search(rf"\b{key}\s*=\s*([-\d.eE+]+)", line)
    return float(match.group(1)) if match else None


def _port_values(text: str) -> list:
    return [float(z) for z in re.findall(r"Port:\S+\s+\S+\s+\S+\s+Num=\d+\s+Z=([\d.]+)\s*Ohm", text, re.IGNORECASE)]


def _port_nums(text: str) -> set:
    return {int(n) for n in re.findall(r"Port:\S+\s+\S+\s+\S+\s+Num=(\d+)", text, re.IGNORECASE)}


def _resistor_values(text: str) -> list:
    return [float(r) for r in re.findall(r"R:\S+\s+\S+\s+\S+\s+R=([\d.eE+]+)\s*Ohm", text, re.IGNORECASE)]


def _has_value(values: list, target: float, tol: float = 0.5) -> bool:
    return any(abs(v - target) <= tol for v in values)


def _tlin_lines(text: str, kinds=("TLIN",)) -> list:
    pattern = r"^\s*(?:" + "|".join(kinds) + r")\b"
    return [line for line in text.splitlines() if re.search(pattern, line, re.IGNORECASE)]


def _has_sparam(text: str) -> bool:
    low = text.lower()
    return "s_param" in low and ("sweep" in low or ("start=" in low and "stop=" in low))


def _cell_name(top_design: str) -> str:
    parts = top_design.split(":")
    return parts[1] if len(parts) >= 3 else ""


def _fresh_ds(ws: dict, since: float):
    cell = ws.get("schematic_cell") or _cell_name(ws.get("top_design", ""))
    cell = cell.lower()
    floor = max(since, ws.get("netlist_mtime", 0.0) - 2)
    fresh = [
        (mtime, p) for p, mtime in ws.get("datasets", [])
        if mtime >= floor and (not cell or p.stem.lower() == cell)
    ]
    return max(fresh, key=lambda t: t[0])[1] if fresh else None


def _schematic(ws: dict, since: float):
    info = ws.get("schematic_info")
    if info and ws.get("schematic_mtime", 0.0) >= since:
        return info
    return None


def _context(ws: dict, since: float):
    fresh = ws.get("netlist") is not None and ws["netlist_mtime"] >= since
    text = _read(ws.get("netlist")) if fresh else ""
    return text, fresh


def detect_exp01(ws: dict, since: float = 0.0) -> dict:
    wrk = ws["path"]
    evidence = {}
    if ws["mtime"] >= since:
        evidence[0] = f"检测到工作区 {wrk.name}"

    info = _schematic(ws, since)
    if info:
        counts = info["counts"]
        terms = info["terms"]
        params = info["params"]
        if counts.get("MLIN", 0) == 1:
            evidence[1] = "原理图中只有 1 段 MLIN"
        if counts.get("MSUB", 0) >= 1:
            evidence[2] = "原理图中存在 MSUB 基板"
        if {t["num"] for t in terms} == {1, 2} and all(abs((t["z"] or 0) - 50) < 0.5 for t in terms):
            evidence[3] = "原理图中有 Num=1/2、Z=50 Ohm 的两个 Term"
        if counts.get("S_Param", 0) >= 1 and params.get("Start") is not None and params.get("Stop") is not None:
            evidence[4] = f"原理图中 S-Param 扫描 {params.get('Start')}–{params.get('Stop')} GHz"
    else:
        text, fresh = _context(ws, since)
        if fresh:
            low = text.lower()
            ports = _port_values(text)
            nums = _port_nums(text)
            if _count(text, "MLIN") == 1:
                evidence[1] = "netlist 中只有 1 段 MLIN"
            if "msub" in low:
                evidence[2] = "netlist 中存在 MSUB 基板定义"
            if nums == {1, 2} and len(ports) == 2 and all(abs(z - 50) < 0.5 for z in ports):
                evidence[3] = "netlist 中恰好是 Num=1/2、Z=50 Ohm 的两个端口"
            if _has_sparam(text):
                evidence[4] = "netlist 中存在 S-Param 控制器及扫描设置"

    ds = _fresh_ds(ws, since)
    if ds:
        evidence[5] = f"检测到本次实验的仿真数据 {ds.name}"
    return evidence


def detect_exp02(ws: dict, since: float = 0.0) -> dict:
    info = _schematic(ws, since)
    evidence = {}
    if info:
        counts = info["counts"]
        terms = info["terms"]
        if counts.get("TLIN", 0) >= 1 and len(terms) == 2 and counts.get("S_Param", 0) >= 1:
            evidence[0] = "原理图中检测到 TLIN、双端口和 S-Param"
        if any(abs((t["z"] or 0) - 100) < 0.5 for t in terms):
            evidence[2] = "原理图中检测到 100 Ω 负载"
        if any(abs(z - 70.7) < 1 for z in info["params_all"].get("Z", [])):
            evidence[3] = "原理图中检测到 70.7 Ω 变换器"
        if counts.get("S_Param", 0) >= 1:
            evidence[4] = "原理图中存在 S-Param 控制器"
    else:
        text, fresh = _context(ws, since)
        if fresh:
            tlin = _tlin_lines(text)
            ports = _port_values(text)
            resistors = _resistor_values(text)
            if len(_port_nums(text)) == 2 and tlin and _has_sparam(text):
                evidence[0] = f"检测到双端口、{len(tlin)} 段 TLIN 和 S-Param"
            if _has_value(ports + resistors, 100):
                evidence[2] = "检测到 100 Ω 负载"
            if any(abs((_param(line, "Z") or 0) - 70.7) < 1 for line in tlin):
                evidence[3] = "检测到 70.7 Ω 的 λ/4 变换器"
            if _has_sparam(text):
                evidence[4] = "检测到 S-Param 控制器"

    # A controller or dataset cannot prove curves were read and bandwidth recorded.
    # This observation step must be confirmed by the student.
    evidence.pop(4, None)
    return evidence


def detect_exp03(ws: dict, since: float = 0.0) -> dict:
    info = _schematic(ws, since)
    evidence = {}
    if info:
        counts = info["counts"]
        terms = info["terms"]
        lines = counts.get("TLIN", 0) + counts.get("TLSC", 0) + counts.get("TLOC", 0)
        has_stub = counts.get("MLSC", 0) + counts.get("MLOC", 0) + counts.get("MLEF", 0) > 0
        if any(abs((t["z"] or 0) - 100) < 0.5 for t in terms) and counts.get("S_Param", 0):
            evidence[0] = "原理图中检测到 100 Ω 负载和 S-Param"
        if lines >= 2:
            evidence[1] = f"原理图中检测到 {lines} 段传输线（含支节）"
        if lines >= 2 and counts.get("S_Param", 0):
            evidence[2] = "原理图中的匹配网络已配置仿真（匹配效果由检查点判定）"
        if counts.get("MLIN", 0) and has_stub:
            evidence[3] = "原理图中检测到 MLIN 与微带支节"
        if counts.get("S_Param", 0):
            evidence[4] = "原理图中存在 S-Param 控制器"
    else:
        text, fresh = _context(ws, since)
        if fresh:
            low = text.lower()
            tlin = _tlin_lines(text, ("TLIN", "TLSC", "TLOC"))
            ports = _port_values(text)
            resistors = _resistor_values(text)
            has_stub = any(_count(text, k) for k in ("MLSC", "MLOC", "MLEF"))
            if _has_value(ports + resistors, 100) and _has_sparam(text):
                evidence[0] = "检测到 100 Ω 负载的 S 参数仿真"
            if len(tlin) >= 2:
                evidence[1] = f"检测到 {len(tlin)} 段传输线（含支节）"
            if len(tlin) >= 2 and _has_sparam(text):
                evidence[2] = "匹配网络已参与仿真（匹配效果由检查点判定）"
            if _count(text, "MLIN") and has_stub:
                evidence[3] = "检测到 MLIN 与微带支节结构"
            if _has_sparam(text):
                evidence[4] = "检测到 S-Param 控制器"

    ds = _fresh_ds(ws, since)
    if ds:
        evidence[4] = f"检测到本次仿真数据 {ds.name}"
    return evidence


def detect_exp04(ws: dict, since: float = 0.0) -> dict:
    info = _schematic(ws, since)
    evidence = {}
    if info:
        counts = info["counts"]
        if counts.get("MSUB", 0) and counts.get("MLIN", 0) >= 5 and len(info["terms"]) >= 2:
            evidence[1] = "原理图中检测到 MSUB、至少 5 段 MLIN 和双端口"
        if counts.get("MSTEP", 0) >= 4:
            evidence[2] = f"原理图中检测到 {counts.get('MSTEP', 0)} 个 MSTEP"
        if len(info["terms"]) >= 2 and counts.get("S_Param", 0):
            evidence[3] = "原理图中检测到双端口 S-Param"
        if counts.get("S_Param", 0):
            evidence[4] = "原理图中存在 S-Param 控制器"
    else:
        text, fresh = _context(ws, since)
        if fresh:
            low = text.lower()
            ports = _port_values(text)
            if "msub" in low and _count(text, "MLIN") >= 5 and len(_port_nums(text)) == 2:
                evidence[1] = "检测到 MSUB、至少 5 段 MLIN 和双端口"
            if _count(text, "MSTEP") >= 4:
                evidence[2] = f"检测到 {_count(text, 'MSTEP')} 个 MSTEP"
            if len(ports) >= 2 and _has_sparam(text):
                evidence[3] = "检测到双端口 S 参数扫描"
            if _has_sparam(text):
                evidence[4] = "检测到 S-Param 控制器"

    ds = _fresh_ds(ws, since)
    if ds:
        evidence[4] = f"检测到本次仿真数据 {ds.name}"
    return evidence


def detect_exp05(ws: dict, since: float = 0.0) -> dict:
    info = _schematic(ws, since)
    evidence = {}
    if info:
        counts = info["counts"]
        nums = {t["num"] for t in info["terms"]}
        has_resistor = any(abs(r - 100) < 0.5 for r in info["params_all"].get("R", []))
        if len(nums) >= 3 and counts.get("TLIN", 0) >= 2 and has_resistor:
            evidence[1] = "原理图中检测到三端口、两段 TLIN 和 100 Ω 电阻"
        if len(nums) >= 3 and counts.get("MLIN", 0) >= 2:
            evidence[2] = "原理图中检测到三端口微带线实现"
        if len(nums) >= 3 and counts.get("S_Param", 0):
            evidence[3] = "原理图中检测到三端口 S-Param"
        if counts.get("S_Param", 0):
            evidence[4] = "原理图中存在 S-Param 控制器"
    else:
        text, fresh = _context(ws, since)
        if fresh:
            nums = _port_nums(text)
            tlin = _tlin_lines(text)
            resistors = _resistor_values(text)
            has_resistor = _has_value(resistors, 100)
            if len(nums) >= 3 and len(tlin) >= 2 and has_resistor:
                evidence[1] = "检测到三端口、两段 TLIN 和 100 Ω 隔离电阻"
            if len(nums) >= 3 and has_resistor and _count(text, "MLIN") >= 2:
                evidence[2] = "检测到三端口微带线实现"
            if len(nums) >= 3 and _has_sparam(text):
                evidence[3] = "检测到三端口 S 参数扫描"
            if _has_sparam(text):
                evidence[4] = "检测到 S-Param 控制器"

    ds = _fresh_ds(ws, since)
    if ds:
        evidence[4] = f"检测到本次仿真数据 {ds.name}"
    return evidence


DETECTORS = {
    "exp01_microstrip_sparam": detect_exp01,
    "exp02_transmission_line": detect_exp02,
    "exp03_single_stub": detect_exp03,
    "exp04_stepped_lpf": detect_exp04,
    "exp05_wilkinson": detect_exp05,
}


def detect(exp_id: str, workspace: dict, since: float = 0.0) -> dict:
    fn = DETECTORS.get(exp_id)
    return fn(workspace, since) if fn else {}


def workspace_label(workspace: dict) -> str:
    stamp = time.strftime("%m-%d %H:%M", time.localtime(workspace["mtime"]))
    design = workspace.get("design") or "未保存"
    return f"{workspace['path'].name}（{stamp}，{design}）"
