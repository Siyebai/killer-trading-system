#!/usr/bin/env python3
"""
杀手锏交易系统 - 信号引擎 v7.0
核心改进（基于2026-04-29数据分析）：

修复问题：
1. conf>0.86 信号被CONF_MAX过滤 → conf越高实际胜率反而越低（0.74-0.86最优47.3%）
2. 信号过强 = 行情过度延伸 = 反向概率高 → 反趋势需更大止损
3. 新增资金费率极值过滤：费率>+1std 做多减分，费率<-1std 做空减分

v7.0策略：
- 保留v4.0三因子核心（RSI+BB+动量）
- 新增 D信号：资金费率极值确认
- 置信度计算重构：conf过高时主动降分（超买超卖信号的反常规处理）
- 输出 effective_conf：实际用于过滤的置信度（≠raw conf）
"""
import numpy as np


def ema_val(arr, period):
    k = 2 / (period + 1)
    e = float(arr[0])
    for v in arr[1:]:
        e = v * k + e * (1 - k)
    return e


def calc_rsi(closes, period=14):
    diffs  = [closes[j]-closes[j-1] for j in range(-period, 0)]
    gains  = [max(d, 0) for d in diffs]
    losses = [abs(min(d, 0)) for d in diffs]
    ag, al = np.mean(gains), np.mean(losses)
    return 100 - (100/(1+ag/al)) if al > 0 else 50


def calc_bollinger(closes, period=20):
    window = np.array(closes[-period:])
    mid    = float(np.mean(window))
    std    = float(np.std(window))
    return mid, mid + 2*std, mid - 2*std, std


def calc_atr(highs, lows, closes, period=14):
    trs = [max(highs[j]-lows[j],
               abs(highs[j]-closes[j-1]),
               abs(lows[j]-closes[j-1]))
           for j in range(-period, 0)]
    return float(np.mean(trs))


def pct_change_n(closes, n):
    if len(closes) <= n:
        return 0
    return (closes[-1] - closes[-n-1]) / closes[-n-1] * 100


def generate_signal_v7(closes, highs, lows, opens, volumes, 
                        min_bars=50, funding_rate=None,
                        funding_mean=-0.0000130, funding_std=0.0000411):
    """
    信号生成 v7.0

    funding_rate: 当前资金费率（float，可选）
    funding_mean/std: 历史均值/标准差（默认使用200条历史统计值）
    """
    n = len(closes)
    if n < min_bars:
        return {'direction': 'NEUTRAL', 'confidence': 0,
                'effective_conf': 0, 'reason': 'insufficient_data', 'market': 'N/A'}

    cur  = closes[-1]
    prev = closes[-2] if n >= 2 else cur

    # ── 基础指标 ─────────────────────────────────
    rsi14 = calc_rsi(closes, 14)
    rsi9  = calc_rsi(closes[-10:], 9) if n >= 10 else rsi14
    bb_mid, bb_upper, bb_lower, bb_std = calc_bollinger(closes)
    atr   = calc_atr(highs, lows, closes)
    atr_pct = atr / cur * 100

    bb_pos = (cur - bb_lower) / (bb_upper - bb_lower) if bb_upper != bb_lower else 0.5

    vol_ma = np.mean(volumes[-20:]) if n >= 20 else np.mean(volumes)
    vol_ratio = volumes[-1] / vol_ma if vol_ma > 0 else 1.0

    ema200 = ema_val(closes[-210:], 200) if n >= 210 else np.mean(closes)
    ratio  = cur / ema200
    if   ratio > 1.02: market = 'BULL'
    elif ratio < 0.98: market = 'BEAR'
    else:              market = 'NEUTRAL_MKT'

    ret3 = pct_change_n(closes, 3)
    ret6 = pct_change_n(closes, 6)

    # ── 信号 A：RSI 极端反转 ─────────────────────
    sig_A_long = sig_A_short = False
    A_strength = 0
    if rsi14 <= 28:
        sig_A_long  = True
        A_strength  = (30 - rsi14) / 30
    elif rsi14 >= 72:
        sig_A_short = True
        A_strength  = (rsi14 - 70) / 30

    # ── 信号 B：布林带反转 ─────────────────────────
    sig_B_long = sig_B_short = False
    B_strength = 0
    if bb_pos <= 0.05 and prev < bb_lower:
        sig_B_long  = True
        B_strength  = min((bb_lower - cur) / bb_std, 1.5) / 1.5
    elif bb_pos >= 0.95 and prev > bb_upper:
        sig_B_short = True
        B_strength  = min((cur - bb_upper) / bb_std, 1.5) / 1.5
    if not sig_B_long  and bb_pos <= 0.08:
        sig_B_long  = True; B_strength = max(B_strength, 0.4)
    if not sig_B_short and bb_pos >= 0.92:
        sig_B_short = True; B_strength = max(B_strength, 0.4)

    # ── 信号 C：短期超涨超跌 ────────────────────────
    sig_C_long = sig_C_short = False
    C_strength = 0
    if ret3 < -atr_pct * 1.2:
        sig_C_long  = True
        C_strength  = min(abs(ret3) / (atr_pct * 2), 1.0)
    elif ret3 > atr_pct * 1.2:
        sig_C_short = True
        C_strength  = min(ret3 / (atr_pct * 2), 1.0)
    if not sig_C_long  and ret6 < -atr_pct * 1.8:
        sig_C_long  = True; C_strength = max(C_strength, min(abs(ret6)/(atr_pct*3), 0.8))
    if not sig_C_short and ret6 > atr_pct * 1.8:
        sig_C_short = True; C_strength = max(C_strength, min(ret6/(atr_pct*3), 0.8))

    # ── 信号 D：资金费率极值确认（新增）────────────────
    # 资金费率>+1std → 市场贪婪/过度多头 → 增强做空信号
    # 资金费率<-1std → 市场恐慌/过度空头 → 增强做多信号
    sig_D_long = sig_D_short = False
    D_boost = 0.0
    if funding_rate is not None:
        fr_zscore = (funding_rate - funding_mean) / funding_std if funding_std > 0 else 0
        if fr_zscore > 1.0:    # 费率偏高 → 支持做空
            sig_D_short = True
            D_boost = min(fr_zscore * 0.03, 0.06)   # 最多+6%置信度
        elif fr_zscore < -1.0: # 费率偏低 → 支持做多
            sig_D_long  = True
            D_boost = min(abs(fr_zscore) * 0.03, 0.06)

    # ── 趋势过滤 ────────────────────────────────────
    long_hits  = sum([sig_A_long,  sig_B_long,  sig_C_long])
    short_hits = sum([sig_A_short, sig_B_short, sig_C_short])

    if market == 'BEAR' and ratio < 0.97:
        long_hits = max(0, long_hits - 1)
    if market == 'BULL' and ratio > 1.03:
        short_hits = max(0, short_hits - 1)

    vol_boost = 0.05 if vol_ratio >= 1.5 else 0

    def get_strength(hits_list):
        vals = [s for s, b in hits_list if b]
        return np.mean(vals) if vals else 0

    long_strength  = get_strength([(A_strength,sig_A_long),(B_strength,sig_B_long),(C_strength,sig_C_long)])
    short_strength = get_strength([(A_strength,sig_A_short),(B_strength,sig_B_short),(C_strength,sig_C_short)])

    def build_signal(direction, hits, strength, reasons, d_boost):
        if hits < 2:
            return None
        raw_conf = min(0.45 + hits * 0.15 + strength * 0.20 + vol_boost + d_boost, 0.95)

        # v7.0核心修正：conf过高反而信号质量差（基于历史验证）
        # conf 0.74-0.86 胜率47.3%，conf 0.90+ 胜率39.4%
        # 采用钟形窗口：conf>0.86时对effective_conf做折扣
        if raw_conf > 0.86:
            excess = raw_conf - 0.86
            effective_conf = 0.86 - excess * 0.5  # 超出部分倒扣
        else:
            effective_conf = raw_conf

        # 自适应止损倍数：信号过强时扩大止损（防反杀）
        if raw_conf > 0.90:
            sl_multiplier = 2.5   # 信号过强=行情过度延伸=需要更多缓冲
        elif raw_conf > 0.86:
            sl_multiplier = 2.2
        else:
            sl_multiplier = 2.0   # 标准止损

        return {
            'direction':      direction,
            'confidence':     round(raw_conf, 3),        # 原始置信度（供参考）
            'effective_conf': round(effective_conf, 3),  # 有效置信度（用于过滤）
            'sl_multiplier':  sl_multiplier,
            'reason':         '|'.join(reasons),
            'market':         market,
            'hits':           hits,
            'strength':       round(strength, 3),
            'rsi':            round(rsi14, 2),
            'bb_pos':         round(bb_pos, 3),
            'ret3':           round(ret3, 3),
            'fr_boost':       d_boost,
        }

    long_reasons  = []
    short_reasons = []
    if sig_A_long:   long_reasons.append(f'RSI超卖({rsi14:.0f})')
    if sig_B_long:   long_reasons.append(f'BB下轨({bb_pos:.2f})')
    if sig_C_long:   long_reasons.append(f'超跌({ret3:.1f}%)')
    if sig_D_long:   long_reasons.append(f'FR低({D_boost:+.3f})')
    if sig_A_short:  short_reasons.append(f'RSI超买({rsi14:.0f})')
    if sig_B_short:  short_reasons.append(f'BB上轨({bb_pos:.2f})')
    if sig_C_short:  short_reasons.append(f'超涨({ret3:.1f}%)')
    if sig_D_short:  short_reasons.append(f'FR高({D_boost:+.3f})')

    long_d  = D_boost if sig_D_long  else 0
    short_d = D_boost if sig_D_short else 0

    long_sig  = build_signal('LONG',  long_hits,  long_strength,  long_reasons,  long_d)
    short_sig = build_signal('SHORT', short_hits, short_strength, short_reasons, short_d)

    if long_sig and short_sig:
        return long_sig if long_sig['effective_conf'] >= short_sig['effective_conf'] else short_sig
    elif long_sig:  return long_sig
    elif short_sig: return short_sig

    return {'direction': 'NEUTRAL', 'confidence': 0, 'effective_conf': 0,
            'reason': f'no_trigger(A:{int(sig_A_long)}/{int(sig_A_short)} '
                      f'B:{int(sig_B_long)}/{int(sig_B_short)} '
                      f'C:{int(sig_C_long)}/{int(sig_C_short)})',
            'market': market}
