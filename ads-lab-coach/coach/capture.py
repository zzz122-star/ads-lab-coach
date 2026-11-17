"""Persistent acquisition service; does not depend on an open browser session."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time

from . import db, lab2

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE = ROOT / "data" / "evidence"


def connect():
    conn = sqlite3.connect(db.DB_PATH, timeout=15)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS lab2_runs (
        id TEXT PRIMARY KEY, user TEXT, workspace TEXT, cell TEXT, params TEXT,
        active INTEGER, since REAL, updated REAL, message TEXT);
    CREATE TABLE IF NOT EXISTS lab2_captures (
        run_id TEXT, digest TEXT, ts REAL, summary TEXT, error TEXT, folder TEXT,
        PRIMARY KEY(run_id,digest));
    CREATE TABLE IF NOT EXISTS lab2_service (id INTEGER PRIMARY KEY, heartbeat REAL, error TEXT);
    """)
    return conn


def subscribe(user, workspace, cell, params, active=True):
    key = lab2.run_key(user, workspace, cell, params)
    with connect() as conn:
        conn.execute("UPDATE lab2_runs SET active=0 WHERE user=?", (user,))
        conn.execute("INSERT INTO lab2_runs VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET active=excluded.active, updated=excluded.updated",
                     (key, user, str(workspace), cell, json.dumps(params), int(active), 0, time.time(), "等待采集"))
    return key


def reset(key):
    with connect() as conn:
        # Preserve archived captures; a timestamp starts a fresh validation round.
        conn.execute("UPDATE lab2_runs SET since=?, message=? WHERE id=?", (time.time(), "已开始新一轮，请重新仿真各状态", key))


def view(key):
    with connect() as conn:
        run = conn.execute("SELECT since,message FROM lab2_runs WHERE id=?", (key,)).fetchone()
        records = conn.execute("SELECT ts,summary,error,folder FROM lab2_captures WHERE run_id=? AND ts>=? ORDER BY ts", (key, run[0] if run else 0)).fetchall()
        heartbeat = conn.execute("SELECT heartbeat,error FROM lab2_service WHERE id=1").fetchone()
    stages = {}
    for ts, summary, error, folder in records:
        if not error:
            summary = json.loads(summary)
            summary.update(ts=ts, folder=folder)
            stages[summary["stage"]] = summary
    matched_band = next((json.loads(s) for _, s, e, _ in reversed(records) if not e and json.loads(s).get("bandwidth_pass")), None)
    passed = ["baseline" in stages, "short" in stages and "open" in stages, "unmatched" in stages, "matched" in stages, matched_band is not None]
    return {"stages": stages, "passed": passed, "bandwidth": matched_band, "message": run[1] if run else "等待配置", "alive": bool(heartbeat and time.time()-heartbeat[0] < 15), "service_error": heartbeat[1] if heartbeat else "", "records": records}


def reader_python():
    configured = os.environ.get("ADS_PYTHON")
    if configured and Path(configured).is_file():
        return configured
    candidates = sorted(Path("C:/Program Files/Keysight").glob("ADS*/tools/python/python.exe"), reverse=True)
    if not candidates:
        raise RuntimeError("未找到 ADS Python；请配置 ADS_PYTHON，不能用文件存在代替结果判定")
    return str(candidates[0])


def read_dataset(path):
    result = subprocess.run([reader_python(), str(ROOT / "coach" / "dataset_reader.py"), str(path)], capture_output=True, text=True, timeout=40,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        data = json.loads(result.stdout)
    except (ValueError, TypeError):
        raise RuntimeError("ADS 数据接口未能读取结果：" + (result.stderr or result.stdout)[-800:])
    if result.returncode or "error" in data:
        raise RuntimeError(data.get("error", result.stderr))
    return data


def stamp(path):
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


class Collector:
    def __init__(self):
        self.stable = {}
        self.processed = {}

    def tick(self):
        with connect() as conn:
            runs = conn.execute("SELECT id,workspace,cell,params,since FROM lab2_runs WHERE active=1").fetchall()
            conn.execute("INSERT INTO lab2_service VALUES (1,?,?) ON CONFLICT(id) DO UPDATE SET heartbeat=excluded.heartbeat,error=excluded.error", (time.time(), ""))
        for key, workspace, cell, params, since in runs:
            try:
                message = self.collect(key, Path(workspace), cell, json.loads(params), since)
            except Exception as exc:
                message = f"采集未完成：{exc}"
            with connect() as conn:
                conn.execute("UPDATE lab2_runs SET message=? WHERE id=?", (message, key))
        with connect() as conn:
            conn.execute("INSERT INTO lab2_service VALUES (1,?,?) ON CONFLICT(id) DO UPDATE SET heartbeat=excluded.heartbeat,error=excluded.error", (time.time(), ""))

    def collect(self, key, workspace, cell, params, since):
        net = workspace / "netlist.log"
        dataset = workspace / "data" / f"{cell}.ds"
        if not net.exists() or not dataset.exists():
            return f"等待 {cell} 仿真：缺少 netlist.log 或 data/{cell}.ds。旧结果若已覆盖，需要重跑。"
        signature = (stamp(net), stamp(dataset))
        if self.stable.get(key) != signature:
            self.stable[key] = signature
            return "检测到文件变化，等待写入稳定"
        if dataset.stat().st_mtime < max(since, net.stat().st_mtime-2):
            return "等待本轮仿真结果：现有数据早于当前网表或重新开始时间"
        if self.processed.get(key) == (signature, since):
            with connect() as conn:
                return conn.execute("SELECT message FROM lab2_runs WHERE id=?", (key,)).fetchone()[0]
        text = net.read_text(encoding="utf-8", errors="replace")
        top = __import__("re").search(r'Top Design:\s*"([^\"]+)"', text)
        if not top or top.group(1).split(":")[1] != cell:
            return f"当前网表不是所选设计 {cell}；请在 {cell} 中运行仿真"
        schematics = list(workspace.glob(f"*/{cell}/schematic/sch.oa"))
        if any(s.stat().st_mtime > net.stat().st_mtime+2 for s in schematics):
            return "原理图在生成网表后又被保存，请重新仿真以验证最新电路"
        net_bytes, ds_bytes = net.read_bytes(), dataset.read_bytes()
        if signature != (stamp(net), stamp(dataset)):
            return "仿真文件仍在变化，等待下一次采集"
        digest = hashlib.sha256(net_bytes + ds_bytes).hexdigest()
        with connect() as conn:
            existing = conn.execute("SELECT ts,error FROM lab2_captures WHERE run_id=? AND digest=?", (key, digest)).fetchone()
        if existing and existing[0] >= since:
            self.processed[key] = (signature, since)
            return "已留存本次结果" if not existing[1] else existing[1]
        folder = ARCHIVE / key / digest[:20]
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "netlist.log").write_bytes(net_bytes)
        (folder / "result.ds").write_bytes(ds_bytes)
        summary, error = {}, ""
        try:
            data = read_dataset(folder / "result.ds")
            (folder / "result.json").write_text(json.dumps(data), encoding="utf-8")
            summary = lab2.validate(text, data, params)
        except Exception as exc:
            error = str(exc)
        record_ts = dataset.stat().st_mtime
        with connect() as conn:
            conn.execute("INSERT INTO lab2_captures VALUES (?,?,?,?,?,?) ON CONFLICT(run_id,digest) DO UPDATE SET ts=excluded.ts,summary=excluded.summary,error=excluded.error", (key, digest, record_ts, json.dumps(summary), error, str(folder)))
        self.processed[key] = (signature, since)
        return error or f"已验证并留存：{summary['stage']}"


def serve(stop_event):
    collector = Collector()
    while not stop_event.is_set():
        try:
            collector.tick()
        except Exception as exc:
            with connect() as conn:
                conn.execute("INSERT OR REPLACE INTO lab2_service VALUES (1,?,?)", (time.time(), str(exc)))
        stop_event.wait(1)
