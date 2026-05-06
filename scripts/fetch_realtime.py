#!/usr/bin/env python3
"""
fetch_realtime.py — 从 Binance 拉取最新 K 线数据（免认证公开接口）
支持：3m / 5m / 15m，BTC/ETH/SOL/BNB，最近 90 天
"""
import requests, json, time, os, sys
from datetime import datetime, timezone

BASE_URL = "https://fapi.binance.com"  # 永续合约
SPOT_URL = "https://api.binance.com"   # 现货

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
os.makedirs(DATA_DIR, exist_ok=True)

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
INTERVALS = {
    "3m":  {"days": 90, "limit": 1500},
    "5m":  {"days": 60, "limit": 1500},
    "15m": {"days": 90, "limit": 1500},
}

def fetch_klines(symbol: str, interval: str, days: int, limit: int = 1500) -> list:
    """分页拉取历史K线，返回 [ts, o, h, l, c, vol, taker_buy_vol] 列表"""
    end_ms   = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = end_ms - days * 86400 * 1000
    all_data = []
    url = f"{BASE_URL}/fapi/v1/klines"

    while start_ms < end_ms:
        params = {
            "symbol":    symbol,
            "interval":  interval,
            "startTime": start_ms,
            "endTime":   end_ms,
            "limit":     limit,
        }
        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            rows = resp.json()
        except Exception as e:
            print(f"  ⚠️  {symbol} {interval} 请求失败: {e}")
            break

        if not rows:
            break

        for r in rows:
            all_data.append([
                int(r[0]),           # open_time ms
                float(r[1]),         # open
                float(r[2]),         # high
                float(r[3]),         # low
                float(r[4]),         # close
                float(r[5]),         # volume
                float(r[9]),         # taker_buy_base_asset_volume
            ])

        last_ts = int(rows[-1][0])
        if last_ts <= start_ms:
            break
        start_ms = last_ts + 1
        time.sleep(0.12)  # 避免触发速率限制

    # 去重 + 排序
    seen = set(); out = []
    for row in all_data:
        if row[0] not in seen:
            seen.add(row[0]); out.append(row)
    out.sort(key=lambda x: x[0])
    return out


def main():
    print(f"{'='*60}")
    print(f"  Binance 真实数据下载 — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}")

    for symbol in SYMBOLS:
        for interval, cfg in INTERVALS.items():
            fname = f"{symbol}_{interval}_live.json"
            fpath = os.path.join(DATA_DIR, fname)

            print(f"⏬  {symbol} {interval} ({cfg['days']}天)...", end=" ", flush=True)
            rows = fetch_klines(symbol, interval, cfg["days"], cfg["limit"])

            if len(rows) < 100:
                print(f"❌ 数据不足 ({len(rows)} 根)")
                continue

            with open(fpath, "w") as f:
                json.dump(rows, f, separators=(",", ":"))

            print(f"✅ {len(rows)} 根 → {fname}")

    print(f"\n数据保存至: {DATA_DIR}")
    print("完成！")


if __name__ == "__main__":
    main()
