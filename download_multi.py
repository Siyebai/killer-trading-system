#!/usr/bin/env python3
"""批量下载多品种 K 线数据"""
import subprocess, json, time

def download_symbol(symbol, limit=1000):
    print(f"下载 {symbol}...")
    all_klines = []
    start_time = None
    
    for i in range(10):  # 最多 10 批
        cmd = ['binance-cli', 'futures-usds', 'kline-candlestick-data',
               '--symbol', symbol, '--interval', '1m', '--limit', str(limit)]
        if start_time:
            cmd.extend(['--start-time', str(start_time)])
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  错误：{result.stderr[:100]}")
            break
        
        klines = json.loads(result.stdout)
        if not klines:
            break
        
        all_klines.extend(klines)
        start_time = klines[-1][0] + 1
        print(f"  已下载 {len(all_klines)} 根")
        time.sleep(0.3)
    
    with open(f'{symbol.lower()}_7d.json', 'w') as f:
        json.dump(all_klines, f)
    print(f"完成！{symbol} 共 {len(all_klines)} 根 K 线\n")
    return len(all_klines)

if __name__ == '__main__':
    symbols = ['ETHUSDT', 'SOLUSDT', 'BNBUSDT']
    for sym in symbols:
        download_symbol(sym)
    print("全部完成！")
