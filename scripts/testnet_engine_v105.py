#!/usr/bin/env python3
"""
杀手锏 Testnet 执行引擎 v1.0.5
策略: v4.0 均值回归  品种: BTCUSDT + SOLUSDT  周期: 1H
模式: Testnet 纸交易（不动真实资金）
"""
import json, time, hmac, hashlib, urllib.request, urllib.parse, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from signal_engine_v4 import generate_signal_v4, calc_atr

# ── 配置 ─────────────────────────────────────────────────────────
TESTNET_BASE = "https://testnet.binancefuture.com"
API_KEY  = "Viubn6nQeiIIo5s2JMjtzvsH4GiSV32LZzyChHnSsIQuAAJgFUFvtcSwMlQhiIMU"
API_SEC  = "c56EysrokO9u8G82bXQp3h0sgx93tYDJowcQGEQ3rr84gefIa8GwZkPk0PBCNsFJ"

SYMBOLS   = ["BTCUSDT", "SOLUSDT"]
INTERVAL  = "1h"
CAPITAL   = 10000.0   # Testnet 虚拟资金
RISK_PCT  = 0.05      # 5% 每笔风险
SL_ATR    = 2.0
TP_ATR    = 3.5
MAX_HOLD  = 24        # 最大持仓根数
CONF_MIN  = 0.74
CONF_MAX  = 0.86
LEVERAGE  = 5         # 5倍杠杆
LOG_DIR   = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
CST       = timezone(timedelta(hours=8))


def now_cst():
    return datetime.now(tz=CST).strftime("%Y-%m-%d %H:%M:%S CST")


def sign_request(params: dict) -> str:
    qs = urllib.parse.urlencode(params)
    sig = hmac.new(API_SEC.encode(), qs.encode(), hashlib.sha256).hexdigest()
    return f"{qs}&signature={sig}"


def api_get(path, params=None, signed=False):
    p = params or {}
    if signed:
        p["timestamp"] = int(time.time() * 1000)
        qs = sign_request(p)
    else:
        qs = urllib.parse.urlencode(p)
    url = f"{TESTNET_BASE}{path}?{qs}"
    req = urllib.request.Request(url, headers={"X-MBX-APIKEY": API_KEY})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode()}"
    except Exception as e:
        return None, str(e)


def api_post(path, params: dict):
    params["timestamp"] = int(time.time() * 1000)
    body = sign_request(params).encode()
    req = urllib.request.Request(
        f"{TESTNET_BASE}{path}", data=body, method="POST",
        headers={"X-MBX-APIKEY": API_KEY, "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode()}"
    except Exception as e:
        return None, str(e)


def get_klines(symbol, limit=60):
    data, err = api_get("/fapi/v1/klines", {"symbol": symbol, "interval": INTERVAL, "limit": limit})
    if err or not data:
        return None, None, None, None, None
    closes  = [float(b[4]) for b in data]
    highs   = [float(b[2]) for b in data]
    lows    = [float(b[3]) for b in data]
    opens   = [float(b[1]) for b in data]
    volumes = [float(b[5]) for b in data]
    return closes, highs, lows, opens, volumes


def get_balance():
    data, err = api_get("/fapi/v2/balance", signed=True)
    if err or not data:
        return None, err
    usdt = next((a for a in data if a.get("asset") == "USDT"), None)
    return float(usdt["availableBalance"]) if usdt else None, err


def get_position(symbol):
    data, err = api_get("/fapi/v2/positionRisk", {"symbol": symbol}, signed=True)
    if err or not data:
        return None, err
    return data[0] if data else None, err


def set_leverage(symbol, lev):
    return api_post("/fapi/v1/leverage", {"symbol": symbol, "leverage": lev})


def place_order(symbol, side, qty, sl_price, tp_price):
    """下市价单 + 止损 + 止盈"""
    results = {}
    # 主单
    r, e = api_post("/fapi/v1/order", {
        "symbol": symbol, "side": side, "type": "MARKET",
        "quantity": qty, "reduceOnly": "false"})
    results["entry"] = r or e

    if r:  # 主单成功才挂止损止盈
        close_side = "SELL" if side == "BUY" else "BUY"
        # 止损
        sl_r, sl_e = api_post("/fapi/v1/order", {
            "symbol": symbol, "side": close_side, "type": "STOP_MARKET",
            "stopPrice": round(sl_price, 2), "closePosition": "true"})
        results["sl"] = sl_r or sl_e
        # 止盈
        tp_r, tp_e = api_post("/fapi/v1/order", {
            "symbol": symbol, "side": close_side, "type": "TAKE_PROFIT_MARKET",
            "stopPrice": round(tp_price, 2), "closePosition": "true"})
        results["tp"] = tp_r or tp_e
    return results


def calc_qty(symbol, price, balance):
    """计算下单数量（风险 = balance × RISK_PCT）"""
    risk_usdt = balance * RISK_PCT
    atr_pct = 0.02  # 估算2%ATR
    qty_raw = (risk_usdt / (price * atr_pct * SL_ATR)) * LEVERAGE
    # 最小精度处理
    step = 0.001 if "BTC" in symbol else 0.1
    qty = max(round(qty_raw / step) * step, step)
    return round(qty, 3)


def run_once():
    """执行一次信号扫描+下单"""
    log_entries = []
    print(f"\n{'='*60}")
    print(f"扫描时间: {now_cst()}")

    balance, err = get_balance()
    if balance is None:
        print(f"❌ 获取余额失败: {err}")
        return
    print(f"账户余额: ${balance:,.2f} USDT")

    for symbol in SYMBOLS:
        print(f"\n── {symbol} ──")

        # 获取K线
        closes, highs, lows, opens, volumes = get_klines(symbol, limit=60)
        if closes is None:
            print(f"  ❌ K线获取失败")
            continue

        cur_price = closes[-1]
        print(f"  当前价格: ${cur_price:,.4f}")

        # 检查现有仓位
        pos, err = get_position(symbol)
        if pos and float(pos.get("positionAmt", 0)) != 0:
            amt = float(pos["positionAmt"])
            upnl = float(pos.get("unRealizedProfit", 0))
            entry_p = float(pos.get("entryPrice", 0))
            print(f"  持仓中: {amt} 张  入场价: ${entry_p:.4f}  未实现盈亏: ${upnl:+.2f}")
            continue

        # 生成信号
        sig = generate_signal_v4(closes, highs, lows, opens, volumes)
        direction = sig.get("direction", "NEUTRAL")
        conf = sig.get("confidence", 0)
        print(f"  信号: {direction}  置信度: {conf:.2f}  原因: {sig.get('reason','')}")

        if direction == "NEUTRAL" or conf < CONF_MIN or conf > CONF_MAX:
            print(f"  → 无交易信号")
            continue

        # 计算止损止盈
        atr = calc_atr(highs, lows, closes, 14)
        if direction == "LONG":
            sl_price = cur_price - atr * SL_ATR
            tp_price = cur_price + atr * TP_ATR
            side = "BUY"
        else:
            sl_price = cur_price + atr * SL_ATR
            tp_price = cur_price - atr * TP_ATR
            side = "SELL"

        qty = calc_qty(symbol, cur_price, balance)
        print(f"  → {direction} 入场  SL: ${sl_price:.2f}  TP: ${tp_price:.2f}  数量: {qty}")

        # 设置杠杆
        set_leverage(symbol, LEVERAGE)
        time.sleep(0.3)

        # 下单
        result = place_order(symbol, side, qty, sl_price, tp_price)
        entry_r = result.get("entry")
        if isinstance(entry_r, dict) and entry_r.get("orderId"):
            print(f"  ✅ 下单成功  OrderId: {entry_r['orderId']}  成交价: {entry_r.get('avgPrice','待成交')}")
            log_entries.append({
                "time": now_cst(), "symbol": symbol, "direction": direction,
                "conf": conf, "entry_price": cur_price, "sl": sl_price, "tp": tp_price,
                "qty": qty, "atr": atr, "order_id": entry_r.get("orderId")
            })
        else:
            print(f"  ❌ 下单失败: {entry_r}")

    # 保存日志
    if log_entries:
        log_file = LOG_DIR / f"testnet_{datetime.now(tz=CST).strftime('%Y%m%d')}.json"
        existing = []
        if log_file.exists():
            with open(log_file) as f:
                existing = json.load(f)
        existing.extend(log_entries)
        with open(log_file, "w") as f:
            json.dump(existing, f, indent=2)
        print(f"\n日志已保存: {log_file.name}")


def run_monitor():
    """72小时持续监控主循环（每小时执行一次）"""
    print(f"杀手锏 Testnet 执行引擎 v1.0.5 启动")
    print(f"策略: v4.0均值回归  品种: {SYMBOLS}  周期: {INTERVAL}")
    print(f"风险: {RISK_PCT*100:.0f}%/笔  SL: {SL_ATR}ATR  TP: {TP_ATR}ATR  杠杆: {LEVERAGE}x")
    print(f"启动时间: {now_cst()}")

    start_time = time.time()
    hours_72 = 72 * 3600

    while time.time() - start_time < hours_72:
        try:
            run_once()
        except Exception as e:
            print(f"[{now_cst()}] ❌ 执行异常: {e}")

        elapsed_h = (time.time() - start_time) / 3600
        print(f"\n已运行: {elapsed_h:.1f}h / 72h  下次扫描: 1小时后")
        time.sleep(3600)

    print(f"\n✅ 72小时纸交易完成  结束时间: {now_cst()}")


if __name__ == "__main__":
    import sys
    if "--once" in sys.argv:
        run_once()
    else:
        run_monitor()
