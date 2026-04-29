#!/usr/bin/env python3
"""
杀手锏 信号引擎 v5.0
策略融合三层：
  Layer 1 — 均值回归（升级版 v4.0→v5.0）
    • BB 2.5σ + RSI OB70/OS30 + 量比过滤
  Layer 2 — 趋势动量（新增）
    • EMA20/50 + MACD柱状图交叉 + RSI中性区确认
  Layer 3 — 资金费率套利（新增）
    • funding_rate > +0.05% → 做空（多头付费，市场过热）
    • funding_rate < -0.05% → 做多（空头付费，市场过恐）
  Layer 4 — 订单流不平衡 OFI（新增）
    • taker_buy_vol / total_vol > 0.65 → 多头强势
    • taker_buy_vol / total_vol < 0.35 → 空头强势

信号融合规则：
  • 任意2层同向 → 入场，conf按命中层数计算
  • 资金费率层单独也可触发（高置信度）
  • OFI与均值回归/动量叠加时 conf+0.1
"""
import numpy as np


# ─── 基础指标 ────────────────────────────────────────────────

def ema_val(arr, period):
    k = 2 / (period + 1)
    e = float(arr[0])
    for v in arr[1:]:
        e = v * k + e * (1 - k)
    return e


def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    diffs  = np.diff(closes[-period - 1:])
    gains  = np.maximum(diffs, 0)
    losses = np.abs(np.minimum(diffs, 0))
    ag, al = gains.mean(), losses.mean()
    if al == 0:
        return 100.0 if ag > 0 else 50.0
    return float(100 - 100 / (1 + ag / al))


def calc_bollinger(closes, period=20, n_std=2.5):
    if len(closes) < period:
        mid = float(np.mean(closes))
        return mid, mid, mid, 0.0
    window = np.array(closes[-period:])
    mid    = float(window.mean())
    std    = float(window.std())
    return mid, mid + n_std * std, mid - n_std * std, std


def calc_atr(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return 0.0
    trs = np.maximum(
        np.array(highs[-period:]) - np.array(lows[-period:]),
        np.maximum(
            np.abs(np.array(highs[-period:]) - np.array(closes[-period - 1:-1])),
            np.abs(np.array(lows[-period:])  - np.array(closes[-period - 1:-1]))
        )
    )
    return float(trs.mean())


def calc_macd(closes, fast=12, slow=26, signal=9):
    """返回 (macd_hist当前, macd_hist前一根)"""
    if len(closes) < slow + signal:
        return 0.0, 0.0
    c = np.array(closes, dtype=float)
    def ema_np(arr, p):
        k = 2 / (p + 1); e = np.empty(len(arr)); e[0] = arr[0]
        for i in range(1, len(arr)): e[i] = arr[i] * k + e[i - 1] * (1 - k)
        return e
    macd_line = ema_np(c, fast) - ema_np(c, slow)
    sig_line  = ema_np(macd_line, signal)
    hist      = macd_line - sig_line
    return float(hist[-1]), float(hist[-2]) if len(hist) >= 2 else 0.0


def calc_ofi(taker_buy_vols, total_vols, window=5):
    """
    订单流不平衡：taker主动买占比
    > 0.65 多头强势 / < 0.35 空头强势
    """
    if len(taker_buy_vols) < window or len(total_vols) < window:
        return 0.5
    tb = np.array(taker_buy_vols[-window:])
    tv = np.array(total_vols[-window:])
    total = tv.sum()
    if total == 0:
        return 0.5
    return float(tb.sum() / total)


# ─── 主信号生成 ──────────────────────────────────────────────

def generate_signal_v5(
    closes, highs, lows, opens, volumes,
    taker_buy_vols=None,
    funding_rate: float = 0.0,
    min_bars: int = 60
):
    """
    Parameters
    ----------
    closes/highs/lows/opens/volumes : list[float]
        1H 或 15m K线数据（至少min_bars根）
    taker_buy_vols : list[float] | None
        主动买入成交量（来自K线第10列），None时跳过OFI层
    funding_rate : float
        当前资金费率（如 0.0005 = 0.05%），0时跳过资金费率层
    min_bars : int
        最少数据根数

    Returns
    -------
    dict  包含 direction/confidence/reason/layers 等字段
    """
    n = len(closes)
    if n < min_bars:
        return _neutral("insufficient_data")

    cur  = float(closes[-1])
    prev = float(closes[-2]) if n >= 2 else cur

    # ── 指标计算 ────────────────────────────────────────────
    rsi14    = calc_rsi(closes, 14)
    bb_mid, bb_up, bb_lo, bb_std = calc_bollinger(closes, 20, 2.5)
    atr      = calc_atr(highs, lows, closes, 14)
    if atr == 0:
        return _neutral("zero_atr")

    bb_range = bb_up - bb_lo
    if bb_range < 1e-9:
        return _neutral("bb_flat_market")
    bb_pos   = (cur - bb_lo) / bb_range

    macd_h, macd_h_prev = calc_macd(closes)

    # EMA 方向
    ema20 = ema_val(closes[-min(20, n):], min(20, n))
    ema50 = ema_val(closes[-min(50, n):], min(50, n))
    bull  = ema20 > ema50
    bear  = ema20 < ema50

    # 量比（过滤放量噪音）
    vol_ma    = float(np.mean(volumes[-20:])) if n >= 20 else float(volumes[-1])
    vol_ratio = float(volumes[-1]) / vol_ma if vol_ma > 0 else 1.0
    vol_ok    = vol_ratio < 2.0   # 放量超2倍跳过

    # OFI
    ofi = 0.5
    if taker_buy_vols is not None and len(taker_buy_vols) >= 5:
        ofi = calc_ofi(taker_buy_vols, volumes, window=5)

    # ── Layer 1：均值回归 ─────────────────────────────────
    L1_long  = rsi14 < 30 and bb_pos <= 0.10 and vol_ok
    L1_short = rsi14 > 70 and bb_pos >= 0.90 and vol_ok
    # 宽松触发（单一条件但更极端）
    if not L1_long  and rsi14 < 25: L1_long  = vol_ok
    if not L1_short and rsi14 > 75: L1_short = vol_ok

    # ── Layer 2：趋势动量 ─────────────────────────────────
    # MACD柱状图上穿零轴 + EMA方向
    L2_long  = bull and macd_h > 0 and macd_h_prev <= 0 and rsi14 < 65
    L2_short = bear and macd_h < 0 and macd_h_prev >= 0 and rsi14 > 35
    # 顺势RSI超卖/超买（趋势方向+极端RSI）
    if not L2_long  and bull and rsi14 < 35: L2_long  = True
    if not L2_short and bear and rsi14 > 65: L2_short = True

    # ── Layer 3：资金费率套利 ────────────────────────────
    FR_THRESH = 0.0003   # 0.03%，中等阈值
    FR_STRONG = 0.0007   # 0.07%，强烈信号
    L3_long  = funding_rate < -FR_THRESH   # 空头付费→市场超恐→做多
    L3_short = funding_rate >  FR_THRESH   # 多头付费→市场过热→做空
    L3_strong_long  = funding_rate < -FR_STRONG
    L3_strong_short = funding_rate >  FR_STRONG

    # ── Layer 4：OFI ────────────────────────────────────
    L4_long  = ofi > 0.65
    L4_short = ofi < 0.35

    # ── 融合决策 ─────────────────────────────────────────
    long_layers  = [L1_long,  L2_long,  L3_long,  L4_long]
    short_layers = [L1_short, L2_short, L3_short, L4_short]
    long_hits    = sum(long_layers)
    short_hits   = sum(short_layers)

    long_names  = ["均值回归","趋势动量","资金费率","OFI"]
    short_names = ["均值回归","趋势动量","资金费率","OFI"]
    long_reason  = "+".join(n for n, f in zip(long_names,  long_layers)  if f)
    short_reason = "+".join(n for n, f in zip(short_names, short_layers) if f)

    # 置信度计算
    def calc_conf(hits, strong_fr, rsi_extreme, vol_r):
        base  = 0.40 + hits * 0.12
        base += 0.08 if strong_fr   else 0
        base += 0.05 if rsi_extreme else 0
        base += 0.03 if vol_r < 0.8 else 0   # 缩量加分
        return min(round(base, 3), 0.92)

    # 触发条件：
    # a) 任意2层同向
    # b) 资金费率极强单独触发
    # c) L1+L4（均值回归+OFI） 组合

    direction = None
    conf      = 0.0
    reason    = ""

    if long_hits >= 2:
        direction = "LONG"
        conf      = calc_conf(long_hits, L3_strong_long, rsi14 < 28, vol_ratio)
        reason    = long_reason
    elif short_hits >= 2:
        direction = "SHORT"
        conf      = calc_conf(short_hits, L3_strong_short, rsi14 > 72, vol_ratio)
        reason    = short_reason
    elif L3_strong_long:
        direction = "LONG"
        conf      = 0.72
        reason    = "资金费率极强做多"
    elif L3_strong_short:
        direction = "SHORT"
        conf      = 0.72
        reason    = "资金费率极强做空"

    if direction is None:
        layers_info = (f"L1:{int(L1_long)}/{int(L1_short)} "
                       f"L2:{int(L2_long)}/{int(L2_short)} "
                       f"L3:{int(L3_long)}/{int(L3_short)} "
                       f"L4:{int(L4_long)}/{int(L4_short)}")
        return _neutral(f"no_trigger({layers_info})")

    return {
        "direction":  direction,
        "confidence": conf,
        "reason":     reason,
        "layers": {
            "L1_mean_rev": L1_long if direction == "LONG" else L1_short,
            "L2_momentum": L2_long if direction == "LONG" else L2_short,
            "L3_funding":  L3_long if direction == "LONG" else L3_short,
            "L4_ofi":      L4_long if direction == "LONG" else L4_short,
        },
        "indicators": {
            "rsi": round(rsi14, 2),
            "bb_pos": round(bb_pos, 3),
            "ofi": round(ofi, 3),
            "funding_rate": funding_rate,
            "vol_ratio": round(vol_ratio, 2),
            "macd_hist": round(macd_h, 6),
        }
    }


def _neutral(reason):
    return {"direction": "NEUTRAL", "confidence": 0.0, "reason": reason, "layers": {}, "indicators": {}}
