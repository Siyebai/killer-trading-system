#!/usr/bin/env python3
import subprocess, json, time

symbol = 'BTCUSDT'
interval = '1m'
limit = 1000
total_bars = 10080  # 7 days

all_klines = []
start_time = None

print(f"下载 {symbol} {interval} 数据，目标 {total_bars} 根 K 线...")

for i in range(0, total_bars, limit):
    cmd = ['binance-cli', 'futures-usds', 'kline-candlestick-data', 
           '--symbol', symbol, '--interval', interval, '--limit', str(limit)]
    if start_time:
        cmd.extend(['--start-time', str(start_time)])
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"错误：{result.stderr}")
        break
    
    klines = json.loads(result.stdout)
    if not klines:
        print("无更多数据")
        break
    
    all_klines.extend(klines)
    start_time = klines[-1][0] + 1  # 下一批从最后时间 +1ms 开始
    print(f"已下载 {len(all_klines)} 根 K 线")
    time.sleep(0.5)  # 避免限流

with open('btc_7d.json', 'w') as f:
    json.dump(all_klines, f)

print(f"完成！共 {len(all_klines)} 根 K 线，已保存至 btc_7d.json")
