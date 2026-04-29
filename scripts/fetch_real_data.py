#!/usr/bin/env python3
"""
杀手锏交易系统 - 真实币安数据获取器
使用 Binance 公开 API（无需 API Key）获取真实历史 K 线数据
数据用于系统验证和回测（非实盘交易）
"""
import json
import time
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
import sys

BASE_URL = "https://api.binance.com"

def fetch_klines(symbol="BTCUSDT", interval="1h", days=365, output_path=None):
    """
    获取真实 K 线数据
    symbol: 交易对
    interval: K线周期 1m/5m/15m/1h/4h/1d
    days: 获取天数
    """
    print(f"📡 开始获取 {symbol} {interval} 最近 {days} 天数据...")
    
    end_time = int(time.time() * 1000)
    start_time = end_time - days * 24 * 3600 * 1000
    
    all_klines = []
    current_start = start_time
    limit = 1000  # 每次最多1000根
    
    batch = 0
    while current_start < end_time:
        params = urllib.parse.urlencode({
            "symbol": symbol,
            "interval": interval,
            "startTime": current_start,
            "endTime": end_time,
            "limit": limit
        })
        url = f"{BASE_URL}/api/v3/klines?{params}"
        
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
        except Exception as e:
            print(f"❌ 请求失败: {e}")
            time.sleep(2)
            continue
        
        if not data:
            break
            
        all_klines.extend(data)
        batch += 1
        
        last_time = data[-1][0]
        current_start = last_time + 1
        
        print(f"  批次 {batch}: 已获取 {len(all_klines)} 根K线, 最新时间: {datetime.fromtimestamp(last_time/1000).strftime('%Y-%m-%d %H:%M')}")
        
        if len(data) < limit:
            break
            
        time.sleep(0.3)  # 限速保护
    
    # 转换为标准格式
    formatted = []
    for k in all_klines:
        formatted.append({
            "timestamp": k[0],
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
            "close_time": k[6],
            "quote_volume": float(k[7]),
            "trades": int(k[8]),
            "datetime": datetime.fromtimestamp(k[0]/1000).strftime('%Y-%m-%d %H:%M:%S')
        })
    
    print(f"\n✅ 获取完成: 共 {len(formatted)} 根K线")
    print(f"   时间范围: {formatted[0]['datetime']} → {formatted[-1]['datetime']}")
    
    # 保存文件
    if output_path is None:
        output_path = Path(__file__).parent.parent / "data" / f"{symbol}_{interval}_{days}d.json"
    
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(formatted, f)
    
    print(f"   文件保存: {output_path}")
    return formatted


def fetch_funding_rate(symbol="BTCUSDT", limit=500):
    """
    获取资金费率历史（永续合约）
    这是有 alpha 的信号源之一
    """
    print(f"\n📡 获取 {symbol} 资金费率历史...")
    
    params = urllib.parse.urlencode({
        "symbol": symbol,
        "limit": limit
    })
    url = f"{BASE_URL}/fapi/v1/fundingRate?{params}"
    
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"❌ 资金费率获取失败: {e}")
        return []
    
    formatted = []
    for r in data:
        rate = float(r['fundingRate'])
        formatted.append({
            "timestamp": r['fundingTime'],
            "datetime": datetime.fromtimestamp(r['fundingTime']/1000).strftime('%Y-%m-%d %H:%M:%S'),
            "symbol": r['symbol'],
            "funding_rate": rate,
            "funding_rate_pct": rate * 100,
            # 信号判断
            "signal": "SHORT" if rate > 0.001 else ("LONG" if rate < -0.0005 else "NEUTRAL"),
            "signal_strength": min(abs(rate) / 0.001, 1.0)
        })
    
    print(f"✅ 资金费率: {len(formatted)} 条记录")
    if formatted:
        latest = formatted[-1]
        print(f"   最新费率: {latest['funding_rate_pct']:.4f}% ({latest['datetime']})")
        print(f"   信号方向: {latest['signal']} (强度: {latest['signal_strength']:.2f})")
    
    output_path = Path(__file__).parent.parent / "data" / f"{symbol}_funding_rate.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(formatted, f)
    print(f"   文件保存: {output_path}")
    
    return formatted


def fetch_current_price(symbol="BTCUSDT"):
    """获取当前价格"""
    url = f"{BASE_URL}/api/v3/ticker/price?symbol={symbol}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            return float(data['price'])
    except Exception:
        return None


if __name__ == "__main__":
    print("=" * 60)
    print("🚀 杀手锏交易系统 - 真实数据获取器")
    print("=" * 60)
    
    # 当前价格
    price = fetch_current_price()
    if price:
        print(f"\n💰 BTC 当前价格: ${price:,.2f}")
    
    # 获取 1H K线 (365天)
    klines = fetch_klines("BTCUSDT", "1h", days=365)
    
    # 获取资金费率
    funding = fetch_funding_rate("BTCUSDT", limit=500)
    
    print("\n" + "=" * 60)
    print("✅ 数据获取完毕，可用于系统验证")
    print("=" * 60)
