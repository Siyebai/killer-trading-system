# [ARCHIVED by Round 9 Integration - 2025-04-30]
# Reason: No active callers

#!/usr/bin/env python3
"""
杀手锏交易系统 v1.0.3 - 真实数据验证器
用 Binance 真实 1H K线数据跑 60/20/20 样本外验证
"""
import json
import sys
import os
import numpy as np
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

DATA_FILE = Path(__file__).parent.parent / "data" / "BTCUSDT_1h_365d.json"


def load_real_data():
    with open(DATA_FILE) as f:
        raw = json.load(f)
    
    data = {
        "timestamp": [],
        "open": [], "high": [], "low": [], "close": [], "volume": []
    }
    for k in raw:
        data["timestamp"].append(k["timestamp"])
        data["open"].append(k["open"])
        data["high"].append(k["high"])
        data["low"].append(k["low"])
        data["close"].append(k["close"])
        data["volume"].append(k["volume"])
    
    print(f"✅ 加载真实数据: {len(data['close'])} 根K线")
    print(f"   {raw[0]['datetime']} → {raw[-1]['datetime']}")
    print(f"   价格范围: ${min(data['close']):,.0f} ~ ${max(data['close']):,.0f}")
    return data


def calc_indicators(data, i):
    """计算指标（滑窗）"""
    closes = data["close"][:i+1]
    highs  = data["high"][:i+1]
    lows   = data["low"][:i+1]
    vols   = data["volume"][:i+1]
    
    n = len(closes)
    if n < 210:
        return None
    
    # EMA
    def ema(arr, period):
        k = 2 / (period + 1)
        e = arr[0]
        for v in arr[1:]:
            e = v * k + e * (1 - k)
        return e
    
    ema9   = ema(closes[-20:],  9)
    ema21  = ema(closes[-40:], 21)
    ema50  = ema(closes[-80:], 50)
    ema200 = ema(closes[-250:], 200) if n >= 250 else ema(closes, 200)
    
    # RSI(14)
    diffs = [closes[j] - closes[j-1] for j in range(n-14, n)]
    gains = [max(d, 0) for d in diffs]
    losses = [abs(min(d, 0)) for d in diffs]
    ag = sum(gains) / 14
    al = sum(losses) / 14
    rsi = 100 - (100 / (1 + ag/al)) if al > 0 else 50
    
    # MACD
    macd_line = ema(closes[-35:], 12) - ema(closes[-35:], 26)
    macd_prev = ema(closes[-36:-1], 12) - ema(closes[-36:-1], 26)
    
    # ATR(14)
    trs = []
    for j in range(n-14, n):
        tr = max(highs[j] - lows[j],
                 abs(highs[j] - closes[j-1]),
                 abs(lows[j]  - closes[j-1]))
        trs.append(tr)
    atr = sum(trs) / 14
    
    # 成交量
    vol_ma20 = sum(vols[-20:]) / 20
    vol_ratio = vols[-1] / vol_ma20 if vol_ma20 > 0 else 1
    
    cur = closes[-1]
    
    return {
        "close": cur,
        "ema9": ema9, "ema21": ema21, "ema50": ema50, "ema200": ema200,
        "rsi": rsi,
        "macd": macd_line, "macd_prev": macd_prev,
        "atr": atr,
        "vol_ratio": vol_ratio,
        "price_ema200_ratio": cur / ema200
    }


def generate_signal(ind):
    """信号生成（含趋势过滤）"""
    cur     = ind["close"]
    ema9    = ind["ema9"]
    ema21   = ind["ema21"]
    ema50   = ind["ema50"]
    ema200  = ind["ema200"]
    rsi     = ind["rsi"]
    macd    = ind["macd"]
    macd_p  = ind["macd_prev"]
    vol_r   = ind["vol_ratio"]
    ratio   = ind["price_ema200_ratio"]

    # === P0 趋势方向过滤 ===
    if ratio >= 1.005:
        market = "BULL"
    elif ratio <= 0.995:
        market = "BEAR"
    else:
        market = "NEUTRAL"

    # LONG 评分
    long_score = 0
    if cur > ema9 > ema21 > ema50:     long_score += 3
    elif cur > ema9 > ema21:            long_score += 2
    if rsi < 45:                        long_score += 2
    elif rsi < 50:                      long_score += 1
    if macd > 0 and macd_p <= 0:        long_score += 2  # 金叉
    elif macd > macd_p and macd > 0:    long_score += 1
    if vol_r > 1.5:                     long_score += 1

    # SHORT 评分
    short_score = 0
    if cur < ema9 < ema21 < ema50:      short_score += 3
    elif cur < ema9 < ema21:             short_score += 2
    if rsi > 55:                         short_score += 2
    elif rsi > 50:                       short_score += 1
    if macd < 0 and macd_p >= 0:         short_score += 2  # 死叉
    elif macd < macd_p and macd < 0:     short_score += 1
    if vol_r > 1.5:                      short_score += 1

    THRESHOLD = 5

    # 趋势过滤
    if market == "BULL" and long_score >= THRESHOLD:
        conf = min(long_score / 8, 0.95)
        return {"direction": "LONG", "confidence": conf, "market": market}
    elif market == "BEAR" and short_score >= THRESHOLD:
        conf = min(short_score / 8, 0.95)
        return {"direction": "SHORT", "confidence": conf, "market": market}
    elif market == "NEUTRAL":
        if long_score >= THRESHOLD + 1:
            return {"direction": "LONG", "confidence": min(long_score/8, 0.9), "market": market}
        elif short_score >= THRESHOLD + 1:
            return {"direction": "SHORT", "confidence": min(short_score/8, 0.9), "market": market}

    return None


def backtest(data, start_idx, end_idx, label=""):
    """单段回测"""
    capital     = 10000.0
    position    = 0
    entry_price = 0
    stop_loss   = 0
    take_profit = 0
    direction   = None
    trades      = []
    consec_loss = 0
    max_consec  = 0
    blocked_until = -1

    closes = data["close"]

    for i in range(start_idx, end_idx):
        cur = closes[i]

        # === P0-2 熔断检查 ===
        if i <= blocked_until:
            continue

        ind = calc_indicators(data, i)
        if ind is None:
            continue

        # 持仓中检查止损/止盈
        if position != 0:
            hit = False
            if direction == "LONG"  and (cur <= stop_loss or cur >= take_profit):
                hit = True
            if direction == "SHORT" and (cur >= stop_loss or cur <= take_profit):
                hit = True

            if hit:
                slippage = 0.0007
                exit_p = cur * (1 - slippage) if direction == "LONG" else cur * (1 + slippage)
                pnl = (exit_p - entry_price) / entry_price * 100
                if direction == "SHORT":
                    pnl = (entry_price - exit_p) / entry_price * 100

                capital *= (1 + pnl / 100 * 0.02)
                trades.append({
                    "dir": direction, "entry": entry_price, "exit": exit_p,
                    "pnl": pnl, "win": pnl > 0,
                    "time": data["timestamp"][i]
                })

                if pnl < 0:
                    consec_loss += 1
                    max_consec = max(max_consec, consec_loss)
                    # P0-2 熔断：连续5笔亏损暂停24小时（24根1H K线）
                    if consec_loss >= 5:
                        blocked_until = i + 24
                        consec_loss = 0
                else:
                    consec_loss = 0

                position = 0

        # 空仓时找入场信号
        elif position == 0:
            sig = generate_signal(ind)
            if sig and sig["confidence"] >= 0.65:
                atr = ind["atr"]
                slippage = 0.0007
                ep = cur * (1 + slippage) if sig["direction"] == "LONG" else cur * (1 - slippage)

                if sig["direction"] == "LONG":
                    sl = ep - atr * 1.5
                    tp = ep + atr * 3.0
                else:
                    sl = ep + atr * 1.5
                    tp = ep - atr * 3.0

                position = 1
                entry_price = ep
                stop_loss   = sl
                take_profit = tp
                direction   = sig["direction"]

    total  = len(trades)
    wins   = sum(1 for t in trades if t["win"])
    longs  = sum(1 for t in trades if t["dir"] == "LONG")
    shorts = sum(1 for t in trades if t["dir"] == "SHORT")
    wr     = wins / total if total > 0 else 0
    ret    = (capital - 10000) / 10000 * 100

    profit_list = [t["pnl"] for t in trades if t["pnl"] > 0]
    loss_list   = [t["pnl"] for t in trades if t["pnl"] < 0]
    avg_win  = np.mean(profit_list) if profit_list else 0
    avg_loss = np.mean(loss_list)   if loss_list  else 0
    rr = abs(avg_win / avg_loss) if avg_loss != 0 else 0

    return {
        "label": label, "trades": total, "wins": wins,
        "longs": longs, "shorts": shorts,
        "win_rate": wr, "return": ret,
        "avg_win": avg_win, "avg_loss": avg_loss, "rr": rr,
        "max_consec_loss": max_consec, "capital": capital
    }


def run():
    print("=" * 65)
    print("🧪 杀手锏 v1.0.3 × 真实币安数据 — 样本外验证")
    print("=" * 65)

    data  = load_real_data()
    total = len(data["close"])

    # 60/20/20 切分（EMA200需要200根热身，train从200开始）
    t_end = int(total * 0.60)
    v_end = int(total * 0.80)

    print(f"\n📊 数据切分:")
    print(f"   训练集 [0 ~ {t_end}]  : {t_end} 根")
    print(f"   验证集 [{t_end} ~ {v_end}]: {v_end - t_end} 根")
    print(f"   测试集 [{v_end} ~ {total}]: {total - v_end} 根")

    train = backtest(data, 210,   t_end, "训练集")
    val   = backtest(data, t_end, v_end, "验证集")
    test  = backtest(data, v_end, total, "测试集(样本外)")

    print("\n" + "=" * 65)
    print("📈 回测结果")
    print("=" * 65)
    fmt = "{:<16} {:>6} {:>7} {:>8} {:>8} {:>7} {:>8} {:>6}"
    print(fmt.format("数据集", "交易", "胜率", "盈亏比", "收益%", "多/空", "最大连亏", "资金"))
    print("-" * 65)
    for r in [train, val, test]:
        print(fmt.format(
            r["label"],
            r["trades"],
            f"{r['win_rate']*100:.1f}%",
            f"{r['rr']:.2f}:1",
            f"{r['return']:+.2f}%",
            f"{r['longs']}/{r['shorts']}",
            f"{r['max_consec_loss']}笔",
            f"${r['capital']:,.0f}"
        ))
    print("-" * 65)

    # 综合判断
    avg_wr  = (train["win_rate"] + val["win_rate"] + test["win_rate"]) / 3
    all_pos = all(r["return"] > 0 for r in [train, val, test])
    safe    = all(r["max_consec_loss"] < 5 for r in [train, val, test])

    print(f"\n📊 综合指标:")
    print(f"   平均胜率   : {avg_wr*100:.1f}%")
    print(f"   三段都盈利 : {'✅ 是' if all_pos else '❌ 否'}")
    print(f"   熔断风险   : {'✅ 安全' if safe else '⚠️  需关注'}")

    if avg_wr >= 0.55 and all_pos:
        verdict = "✅ 通过样本外验证 — 可进入 Testnet 测试"
    elif avg_wr >= 0.50 and all_pos:
        verdict = "⚠️  基本通过 — 建议先优化 SHORT 策略再上 Testnet"
    else:
        verdict = "❌ 未通过 — 策略需继续优化"

    print(f"\n🎯 最终判断: {verdict}")

    # 保存报告
    report = {
        "date": datetime.now().isoformat(),
        "data_source": "Binance Real API",
        "total_klines": total,
        "train": train, "val": val, "test": test,
        "avg_win_rate": avg_wr,
        "all_positive_return": all_pos,
        "verdict": verdict
    }
    out = Path(__file__).parent.parent / "real_data_validation_report.json"
    with open(out, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n💾 报告已保存: {out.name}")
    print("=" * 65)


if __name__ == "__main__":
    run()
