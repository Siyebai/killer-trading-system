#!/usr/bin/env python3
"""
下载 BTCUSDT 15m 180天数据
binance-cli futures-usds kline，分批拉取，合并去重
"""
import subprocess, json, time
from pathlib import Path
from datetime import datetime, timezone, timedelta

DATA_DIR = Path("/root/.openclaw/workspace/killer-trading-system/data")
OUT_FILE = DATA_DIR / "BTCUSDT_15m_180d.json"
SYMBOL   = "BTCUSDT"
INTERVAL = "15m"
LIMIT    = 1000  # 每批最多1000根
TARGET_DAYS = 180

def ts_to_str(ts_ms):
    return datetime.fromtimestamp(ts_ms/1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")

def download_batch(start_ms=None, end_ms=None):
    cmd = ["binance-cli", "futures-usds", "kline-candlestick-data",
           "--symbol", SYMBOL, "--interval", INTERVAL, "--limit", str(LIMIT)]
    if start_ms: cmd += ["--start-time", str(start_ms)]
    if end_ms:   cmd += ["--end-time",   str(end_ms)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        print(f"  ❌ 错误: {r.stderr[:200]}")
        return []
    data = json.loads(r.stdout)
    return data if isinstance(data, list) else data.get("data", [])

def main():
    now_ms    = int(time.time() * 1000)
    start_ms  = now_ms - TARGET_DAYS * 86400 * 1000
    all_data  = []
    batch_no  = 0
    cur_start = start_ms

    print(f"目标: {SYMBOL} {INTERVAL} 最近{TARGET_DAYS}天")
    print(f"起始: {ts_to_str(start_ms)}  结束: {ts_to_str(now_ms)}")
    print("-"*60)

    while cur_start < now_ms:
        batch_no += 1
        batch = download_batch(start_ms=cur_start)
        if not batch:
            print(f"  批次{batch_no} 空响应，停止")
            break

        # 统一格式成 dict
        normalized = []
        for row in batch:
            if isinstance(row, (list, tuple)):
                normalized.append({
                    "timestamp": row[0], "open": float(row[1]),
                    "high": float(row[2]), "low": float(row[3]),
                    "close": float(row[4]), "volume": float(row[5])
                })
            elif isinstance(row, dict):
                ts = row.get("openTime") or row.get("timestamp") or row.get("ts") or row.get("open_time")
                normalized.append({
                    "timestamp": ts,
                    "open":   float(row.get("open",  row.get("o", 0))),
                    "high":   float(row.get("high",  row.get("h", 0))),
                    "low":    float(row.get("low",   row.get("l", 0))),
                    "close":  float(row.get("close", row.get("c", 0))),
                    "volume": float(row.get("volume",row.get("v", 0))),
                })

        all_data.extend(normalized)
        last_ts = normalized[-1]["timestamp"]
        print(f"  批次{batch_no}: {len(normalized)}根  {ts_to_str(normalized[0]['timestamp'])} → {ts_to_str(last_ts)}  累计:{len(all_data)}")

        if len(normalized) < LIMIT:
            print("  最后一批，完成")
            break
        cur_start = last_ts + 1
        time.sleep(0.25)

    # 去重排序
    seen = {}
    for row in all_data:
        seen[row["timestamp"]] = row
    all_data = sorted(seen.values(), key=lambda x: x["timestamp"])

    # 只保留 TARGET_DAYS 内
    all_data = [r for r in all_data if r["timestamp"] >= start_ms]

    json.dump(all_data, open(OUT_FILE, "w"))
    print(f"\n✅ 保存: {OUT_FILE}")
    print(f"   总计: {len(all_data)} 根K线")
    if all_data:
        print(f"   范围: {ts_to_str(all_data[0]['timestamp'])} → {ts_to_str(all_data[-1]['timestamp'])}")

if __name__ == "__main__":
    main()
