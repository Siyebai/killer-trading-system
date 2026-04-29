#!/usr/bin/env python3
"""
杀手锏 纸交易引擎 v1.0.5
接入真实Binance主网行情，本地模拟执行，不下真实订单
策略: v4.0 均值回归  品种: BTCUSDT + SOLUSDT  周期: 1H
"""
import json, time, subprocess, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from signal_engine_v4 import generate_signal_v4, calc_atr

SYMBOLS   = ["BTCUSDT", "SOLUSDT"]
INTERVAL  = "1h"
CAPITAL   = 10000.0
RISK_PCT  = 0.05
SL_ATR    = 2.0
TP_ATR    = 3.5
MAX_HOLD  = 24
CONF_MIN  = 0.74
CONF_MAX  = 0.86
LOG_DIR   = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
STATE_FILE = LOG_DIR / "paper_trade_state.json"
CST = timezone(timedelta(hours=8))

def now_cst():
    return datetime.now(tz=CST).strftime("%Y-%m-%d %H:%M:%S CST")

def get_klines(symbol, limit=60):
    cmd = ["binance-cli", "futures-usds", "kline-candlestick-data",
           "--symbol", symbol, "--interval", INTERVAL, "--limit", str(limit)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    bars = json.loads(r.stdout)
    return ([float(b[4]) for b in bars], [float(b[2]) for b in bars],
            [float(b[3]) for b in bars], [float(b[1]) for b in bars],
            [float(b[5]) for b in bars], int(bars[-1][0]))

def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE) as f: return json.load(f)
    return {"positions": {}, "trades": [], "capital": CAPITAL,
            "start_time": now_cst(), "scan_count": 0}

def save_state(state):
    with open(STATE_FILE, "w") as f: json.dump(state, f, indent=2)

def run_scan():
    state = load_state()
    state["scan_count"] += 1
    cap = state["capital"]
    peak = max(state.get("peak", CAPITAL), cap)
    state["peak"] = peak
    dd = (peak - cap) / peak * 100

    print(f"\n{'='*62}")
    print(f"⚔️  杀手锏 纸交易  第{state['scan_count']}次扫描  {now_cst()}")
    print(f"账户: ${cap:,.2f}U  峰值: ${peak:,.2f}U  回撤: {dd:.2f}%  总交易: {len(state['trades'])}笔")

    for symbol in SYMBOLS:
        print(f"\n── {symbol} ──")
        try:
            closes, highs, lows, opens, vols, bar_ts = get_klines(symbol, 60)
        except Exception as e:
            print(f"  ❌ 行情获取失败: {e}"); continue

        cur = closes[-1]
        print(f"  当前价: ${cur:,.4f}")
        pos = state["positions"].get(symbol)

        # 检查持仓是否需要平仓
        if pos:
            bars_held = state["scan_count"] - pos["entry_scan"]
            direction = pos["direction"]
            sl, tp = pos["sl"], pos["tp"]
            hit_sl = (direction == "LONG" and cur <= sl) or (direction == "SHORT" and cur >= sl)
            hit_tp = (direction == "LONG" and cur >= tp) or (direction == "SHORT" and cur <= tp)
            timeout = bars_held >= MAX_HOLD

            if hit_sl or hit_tp or timeout:
                exit_price = cur
                pnl_pct = (exit_price - pos["entry"]) / pos["entry"] * 100
                if direction == "SHORT": pnl_pct = -pnl_pct
                pnl_u = cap * RISK_PCT * pnl_pct / 100
                cap += pnl_u
                exit_reason = "止盈✅" if hit_tp else ("止损❌" if hit_sl else "超时⏰")
                trade = {
                    "symbol": symbol, "direction": direction,
                    "entry": pos["entry"], "exit": exit_price,
                    "pnl_pct": round(pnl_pct, 4), "pnl_u": round(pnl_u, 3),
                    "win": pnl_pct > 0, "exit_reason": exit_reason,
                    "bars_held": bars_held, "entry_time": pos["entry_time"], "exit_time": now_cst()
                }
                state["trades"].append(trade)
                del state["positions"][symbol]
                state["capital"] = round(cap, 2)
                mark = "✅" if pnl_pct > 0 else "❌"
                print(f"  {mark} 平仓({exit_reason}) 入场${pos['entry']:.2f} → 出场${exit_price:.2f}  "
                      f"PnL: {pnl_pct:+.3f}%  ${pnl_u:+.2f}U  持仓{bars_held}根")
            else:
                upnl = (cur - pos["entry"]) / pos["entry"] * 100
                if direction == "SHORT": upnl = -upnl
                upnl_u = cap * RISK_PCT * upnl / 100
                print(f"  📊 持仓中({direction}) 入场${pos['entry']:.2f}  持仓{bars_held}根  "
                      f"未实现{upnl:+.3f}% ${upnl_u:+.2f}U")
                continue

        # 无持仓则寻找信号
        if symbol not in state["positions"]:
            sig = generate_signal_v4(closes, highs, lows, opens, vols)
            direction = sig.get("direction", "NEUTRAL")
            conf = sig.get("confidence", 0)

            if direction != "NEUTRAL" and CONF_MIN <= conf <= CONF_MAX:
                atr = calc_atr(highs, lows, closes, 14)
                sl = cur - atr * SL_ATR if direction == "LONG" else cur + atr * SL_ATR
                tp = cur + atr * TP_ATR if direction == "LONG" else cur - atr * TP_ATR
                state["positions"][symbol] = {
                    "direction": direction, "entry": cur, "sl": round(sl, 4),
                    "tp": round(tp, 4), "entry_scan": state["scan_count"],
                    "entry_time": now_cst(), "conf": round(conf, 3), "atr": round(atr, 4)
                }
                print(f"  🎯 开仓({direction}) conf={conf:.2f}  原因: {sig.get('reason','')}")
                print(f"     入场: ${cur:.4f}  SL: ${sl:.4f}  TP: ${tp:.4f}  ATR: {atr:.4f}")
            else:
                print(f"  💤 无信号 ({direction} conf={conf:.2f})")

    # 统计报告
    trades = state["trades"]
    if trades:
        wins = sum(1 for t in trades if t["win"])
        wr = wins / len(trades)
        pnls = [t["pnl_pct"] for t in trades]
        ps = [p for p in pnls if p > 0]; ls = [p for p in pnls if p < 0]
        rr = abs(sum(ps)/len(ps) / (sum(ls)/len(ls))) if ps and ls else 0
        total_pnl = sum(t["pnl_u"] for t in trades)
        print(f"\n  📈 累计: {len(trades)}笔  WR{wr*100:.1f}%  RR{rr:.2f}  总盈亏${total_pnl:+.2f}U  "
              f"净值${state['capital']:,.2f}U")
        if trades:
            t = trades[-1]
            print(f"  最近: {t['symbol']} {t['direction']} {t['exit_reason']} "
                  f"{t['pnl_pct']:+.3f}% ${t['pnl_u']:+.2f}U")

    save_state(state)
    print(f"\n状态已保存: {STATE_FILE.name}")
    return state

def run_72h():
    """72小时持续运行（每小时一次）"""
    print(f"{'='*62}")
    print(f"⚔️  杀手锏 Testnet纸交易引擎 v1.0.5 启动")
    print(f"策略: v4.0均值回归  品种: {SYMBOLS}  周期: {INTERVAL}")
    print(f"资金: ${CAPITAL}U  风险: {RISK_PCT*100:.0f}%/笔  SL:{SL_ATR}ATR TP:{TP_ATR}ATR")
    print(f"启动: {now_cst()}")

    start = time.time()
    target = 72 * 3600

    while time.time() - start < target:
        run_scan()
        elapsed = (time.time() - start) / 3600
        remaining = (target - (time.time() - start)) / 3600
        print(f"\n⏱ 已运行{elapsed:.1f}h  剩余{remaining:.1f}h  下次扫描: 1小时后")
        if time.time() - start + 3600 < target:
            time.sleep(3600)
        else:
            break

    print(f"\n{'='*62}")
    print(f"✅ 72小时纸交易完成  {now_cst()}")
    state = load_state()
    trades = state["trades"]
    if trades:
        wins = sum(1 for t in trades if t["win"])
        total_pnl = sum(t["pnl_u"] for t in trades)
        print(f"总结: {len(trades)}笔  胜率{wins/len(trades)*100:.1f}%  总盈亏${total_pnl:+.2f}U")

if __name__ == "__main__":
    import sys
    if "--once" in sys.argv:
        run_scan()
    else:
        run_72h()
