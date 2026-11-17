from dataclasses import dataclass, field

from . import calc


@dataclass
class CheckResult:
    status: str
    message: str = ""
    hints: list = field(default_factory=list)


CALCS = calc.METRICS


def evaluate(cp: dict, values: dict, params: dict) -> CheckResult:
    kind = cp["type"]
    cid = cp["id"]
    raw = values.get(cid)

    if kind == "confirm":
        if raw is None:
            return CheckResult("pending")
        if raw:
            return CheckResult("pass", cp.get("pass_msg", "通过"))
        return CheckResult("fail", cp.get("fail_msg", "未通过"), cp.get("on_fail", []))

    if kind == "range":
        if raw is None:
            return CheckResult("pending")
        lo, hi = cp.get("min"), cp.get("max")
        if lo is not None and raw < lo:
            return CheckResult("fail", f"{raw:g} 低于下限 {lo:g}", cp.get("on_low", cp.get("on_fail", [])))
        if hi is not None and raw > hi:
            return CheckResult("fail", f"{raw:g} 高于上限 {hi:g}", cp.get("on_high", cp.get("on_fail", [])))
        return CheckResult("pass", cp.get("pass_msg", "通过"))

    if kind == "match_calc":
        if raw is None:
            return CheckResult("pending")
        expected = CALCS[cp["calc"]](params)
        err = abs(raw - expected) / expected * 100
        tol = cp.get("tolerance_pct", 5)
        if err <= tol:
            return CheckResult("pass", f"理论值 {expected:.3f}，偏差 {err:.1f}%")
        return CheckResult("fail", f"理论值 {expected:.3f}，偏差 {err:.1f}% 超出 {tol:g}%", cp.get("on_fail", []))

    if kind == "passivity":
        a, b = (values.get(k) for k in cp["uses"])
        if a is None or b is None:
            return CheckResult("pending")
        power = calc.db_to_mag(a) ** 2 + calc.db_to_mag(b) ** 2
        if power <= 1.0 + 1e-6:
            return CheckResult("pass", f"|S11|²+|S21|² = {power:.4f} ≤ 1")
        return CheckResult("fail", f"|S11|²+|S21|² = {power:.4f} > 1，无源网络不可能", cp.get("on_fail", []))

    raise ValueError(f"unknown checkpoint type: {kind}")


def evaluate_all(checkpoints: list, values: dict, params: dict) -> dict:
    return {cp["id"]: evaluate(cp, values, params) for cp in checkpoints}
