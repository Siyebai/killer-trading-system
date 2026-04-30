# [ARCHIVED by Round 6 Integration - 2026-04-30]
# Reason: No active callers / Superseded by production module

#!/usr/bin/env python3
"""
补充抓取：
1. taker_buy_base_asset_volume（主动买入量）→ 买卖压力
2. 完整资金费率历史（365天）→ 极值信号
"""
import json, time, urllib.request
from pathlib import Path
from datetime import datetime

BASE    = "https://fapi.binance.com"
SPOT    = "https://api.binance.com"
SYMBOL  = "BTCUSDT"
DATA    = Path(__file__).parent.parent / "data"

# ── 1. 抓取带 taker_buy 字段的1H K线 ────────────────────────────
def fetch_klines_full():
    """Binance futures kline: index 9 = taker_buy_base, 10 = taker_buy_quote"""
    url = f"{BASE}/fapi/v1/klines?symbol={SYMBOL}&interval=1h&limit=1500"
    all_bars = []
    # 分批抓8760根
    with open(DATA / "BTCUSDT_1h_365d.json") as f:
        existing = json.load(f)
    ts_list = [d['timestamp'] for d in existing]
    
    print(f"现有数据: {len(existing)}根, 补充taker_buy字段...")
    # 分批请求
    batch_size = 1500
    results = {}
    for start_i in range(0, len(ts_list), batch_size):
        start_ts = ts_list[start_i]
        url_b = f"{BASE}/fapi/v1/klines?symbol={SYMBOL}&interval=1h&limit={batch_size}&startTime={start_ts}"
        try:
            with urllib.request.urlopen(url_b, timeout=15) as r:
                data = json.loads(r.read())
            for bar in data:
                results[bar[0]] = {
                    'taker_buy_vol': float(bar[9]),
                    'taker_buy_quote': float(bar[10])
                }
            print(f"  批次{start_i//batch_size+1}: {len(data)}根")
            time.sleep(0.3)
        except Exception as e:
            print(f"  批次{start_i//batch_size+1}失败: {e}")
    
    # 合并
    merged = []
    for d in existing:
        extra = results.get(d['timestamp'], {})
        merged.append({**d, **extra})
    
    out = DATA / "BTCUSDT_1h_with_flow.json"
    with open(out, 'w') as f:
        json.dump(merged, f)
    
    have_flow = sum(1 for d in merged if 'taker_buy_vol' in d)
    print(f"合并完成: {len(merged)}根, 其中{have_flow}根有taker_buy字段")
    return merged

# ── 2. 抓取完整资金费率历史 ──────────────────────────────────────
def fetch_funding_full():
    print("\n抓取完整资金费率历史...")
    all_rates = []
    limit = 1000
    end_time = None
    
    for _ in range(20):  # 最多20批
        url = f"{BASE}/fapi/v1/fundingRate?symbol={SYMBOL}&limit={limit}"
        if end_time:
            url += f"&endTime={end_time}"
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                data = json.loads(r.read())
            if not data: break
            all_rates = data + all_rates
            end_time = data[0]['fundingTime'] - 1
            print(f"  已抓{len(all_rates)}条, 最早: {datetime.fromtimestamp(data[0]['fundingTime']/1000).strftime('%Y-%m-%d')}")
            if len(data) < limit: break
            time.sleep(0.3)
        except Exception as e:
            print(f"  失败: {e}"); break
    
    out = DATA / "BTCUSDT_funding_full.json"
    with open(out, 'w') as f:
        json.dump(all_rates, f)
    print(f"资金费率: 共{len(all_rates)}条")
    
    # 统计极值
    rates = [float(r['fundingRate']) for r in all_rates]
    import numpy as np
    p95 = float(np.percentile(rates, 95))
    p5  = float(np.percentile(rates, 5))
    print(f"  均值:{np.mean(rates)*100:.4f}%  P5:{p5*100:.4f}%  P95:{p95*100:.4f}%")
    print(f"  >0.1%次数:{sum(1 for r in rates if r>0.001)}  <-0.05%次数:{sum(1 for r in rates if r<-0.0005)}")
    return all_rates, p5, p95

if __name__ == "__main__":
    fetch_klines_full()
    fetch_funding_full()
