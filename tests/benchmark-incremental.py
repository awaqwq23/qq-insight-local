"""Synthetic full/incremental import benchmark; never opens a real QQ database."""
import argparse
import inspect
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/core"))
from local_assistant.service import AssistantService


def varint(value):
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def field(number, payload):
    return varint((number << 3) | 2) + varint(len(payload)) + payload


def fixtures(root, count=50000, people=1000):
    source = root / "synthetic.db"
    conn = sqlite3.connect(source)
    for table in ("c2c_msg_table", "group_msg_table"):
        conn.execute(f'CREATE TABLE {table}("40001" INTEGER PRIMARY KEY,"40011","40012","40013","40020","40021","40030","40033","40050","40800","40090","40093")')
    body = field(40800, field(45101, ("合成测试消息：明天提交材料。" * 3).encode()))
    conn.executemany('INSERT INTO c2c_msg_table VALUES(?,2,0,0,?,?,?,NULL,?,?,NULL,NULL)',
                     ((i, f"synthetic-{i % people}", f"synthetic-{i % people}", str(900000 + i % people), 1700000000 + i, body) for i in range(1, count + 1)))
    conn.commit()
    conn.close()
    profile = root / "profile_info.db"
    conn = sqlite3.connect(profile)
    conn.execute('CREATE TABLE profile_info_v6("1000","1002","20002","20009","20004")')
    conn.executemany('INSERT INTO profile_info_v6 VALUES(?,?,?,"","")', ((f"synthetic-{i}", str(900000 + i), f"合成联系人{i}") for i in range(people)))
    conn.commit()
    conn.close()
    group = root / "group_info.db"
    conn = sqlite3.connect(group)
    conn.execute('CREATE TABLE group_detail_info_ver1("60001","60007","60026")')
    conn.executemany('INSERT INTO group_detail_info_ver1 VALUES(?,?,"")', ((str(800000+i), f"合成群{i}") for i in range(100)))
    conn.commit()
    conn.close()
    return source, {"profile_info.db": profile, "group_info.db": group}, body


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        source, companions, body = fixtures(root)
        stages = []
        def progress(message):
            stages.append((time.perf_counter(), message))
        service = AssistantService(root / "app", on_progress=progress)
        supported = "import_mode" in inspect.signature(service.import_snapshot).parameters
        measurements = {}
        def measure(label, mode):
            stages.clear()
            start = time.perf_counter()
            result = service.import_snapshot(str(source), "synthetic-benchmark", companion_paths=companions,
                                            **({"import_mode": mode} if supported else {}))
            elapsed = time.perf_counter() - start
            metadata_start = next((stamp for stamp, msg in stages if "联系人与群资料" in msg), None)
            measurements[label] = {"seconds": round(elapsed, 3), "metadata_seconds": round(time.perf_counter() - metadata_start, 3) if metadata_start else None,
                                   "stats": result.get("changes"), "metadata": result.get("metadata")}
        measure("initial_full", "full")
        conn = sqlite3.connect(source)
        conn.executemany('INSERT INTO c2c_msg_table VALUES(?,2,0,0,"synthetic-1","synthetic-1","900001",NULL,?,?,NULL,NULL)',
                         ((i, 1600000000 + i, body) for i in range(50001, 50021)))
        conn.commit()
        conn.close()
        conn = sqlite3.connect(companions["profile_info.db"])
        conn.execute('UPDATE profile_info_v6 SET "20009"="新合成备注" WHERE "1000"="synthetic-1"')
        conn.commit()
        conn.close()
        measure("update_20_late_messages_one_contact", "incremental")
        measure("unchanged_repeat", "incremental")
        if supported:
            measure("forced_full", "full")
        print(json.dumps(measurements, ensure_ascii=False, indent=2))
        if args.output:
            Path(args.output).write_text(json.dumps(measurements, ensure_ascii=False, indent=2), encoding="utf-8")
