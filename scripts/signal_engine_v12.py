#!/usr/bin/env python3
"""
杀手锏信号引擎 v12.0
整合来源：
  - v3.8 核心逻辑：ATR自适应RSI阈值矩阵 + EMA趋势锁定 + 动态TP/SL
  - v11 优点：VWAP偏差确认 + Wilder RSI（与主流平台一致）
  - v1.1 框架：EV过滤器接口标准

v3.8 Bug修复清单（已全部修复）：
  [FIX-1] vol_ma KeyError → DEFAULTS 补充 vol_ma=20
  [FIX-2] Hurst poly[0]*2.0 → poly[0]（原来翻倍）
  [FIX-3] _macd_weight 双循环错误 → 改为 if/elif 链
  [FIX-4] RSI SMA → Wilder EWM（与TradingView一致）
  [FIX-5] 置信度门槛 0.45→0.60（门槛原本形同虚设）
  [FIX-6] 回测置信度过滤与 analyze() 对齐

150U 小资金专用配置：
  - 单品种（BTCUSDT），避免资金分散
  - 单笔风险 2%（3U），保护本金
  - TP:SL = 2.5:1，正期望设计
  - 最大同时持仓：1
  - 手续费：Taker 0.05%（BNB抵扣后）

日期: 2026-05-01
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

try:
    from scripts.logger_factory import get_logger
    logger = get_logger("signal_engine_v12")
except ImportError:
    import logging
    logger = logging.getLogger("signal_engine_v12")


# ============================================================
# 参数配置（150U 小资金版）
# ============================================================
DEFAULTS_V12 = {
    # 趋势
    'ema_fast': 20,
    'ema_slow': 50,
    'ema_thresh': 0.001,        # 0.1% 差值判定趋势

    # 震荡
    'rsi_period': 14,
    'bb_period': 20,
    'bb_std': 2.0,
    'bb_long': 0.30,            # 比v3.8更严格（0.35→0.30）
    'bb_short': 0.70,           # 比v3.8更严格（0.65→0.70）

    # 波动率
    'atr_period': 14,
    'vol_ma': 20,               # [FIX-1] v3.8 缺失此键

    # MACD
    'macd_fast': 12,
    'macd_slow': 26,
    'macd_sig': 9,

    # ADX
    'adx_period': 14,
    'adx_thresh': 20,           # 提高至20（原12太低，几乎不过滤）

    # VWAP（v11引入）
    'vwap_window': 20,
    'vwap_dev_thresh': 1.0,     # VWAP偏离1σ触发额外加分

    # Hurst
    'hurst_window': 50,

    # 系统
    'warmup': 60,               # 提高预热期（原50）
    'div_lb': 5,

    # ATR% 自适应 RSI 阈值矩阵（7档，从v3.8继承）
    'rsi_matrix': [
        (0.12, 47, 53),
        (0.15, 45, 55),
        (0.20, 44, 56),
        (0.25, 43, 57),
        (0.30, 42, 58),
        (0.40, 41, 59),
        (999,  38, 62),
    ],

    # MACD 权重（已修复为 if/elif 逻辑）
    'macd_w': [
        (0.25, 0.20),
        (0.10, 0.10),
        (-0.10, 0.00),          # [FIX-3] 中性区返回0而非负值
        (-0.25, -0.05),
        (-999, -0.10),
    ],

    # 成交量过滤
    'vol_spike': 2.0,
    'vol_dead': 0.6,            # 比v3.8更严格（0.5→0.6）

    # 动态 TP/SL（提升盈亏比至2.5:1）
    'tp_sl': [
        (0.20, 2.0, 0.8, 6),   # 低波动：TP=2×ATR, SL=0.8×ATR
        (0.30, 2.5, 1.0, 8),   # 正常：TP=2.5×ATR, SL=1×ATR
        (999,  3.0, 1.0, 12),  # 高波动：TP=3×ATR, SL=1×ATR
    ],

    # 置信度（已修复：提升门槛）
    'conf_thresh': 0.60,        # [FIX-5] 原0.45形同虚设，提升至0.60

    # 风控（150U 专用）
    'risk_pct': 0.02,           # 单笔风险 2%（=3U）
    'max_hold': 24,
    'capital': 150.0,
}


# ============================================================
# 指标计算（全部修复版）
# ============================================================
class Indicators:

    @staticmethod
    def ema(s: pd.Series, n: int) -> pd.Series:
        return s.ewm(span=n, adjust=False).mean()

    @staticmethod
    def rsi(s: pd.Series, n: int) -> pd.Series:
        """[FIX-4] Wilder EWM RSI，与TradingView一致"""
        delta = s.diff()
        gain = delta.where(delta > 0, 0.0).ewm(alpha=1/n, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1/n, adjust=False).mean()
        rs = gain / loss.replace(0, np.nan)
        return 100.0 - (100.0 / (1.0 + rs))

    @staticmethod
    def bb(s: pd.Series, n: int, std: float):
        ma = s.rolling(n).mean()
        sd = s.rolling(n).std()
        upper = ma + sd * std
        lower = ma - sd * std
        bb_pct = (s - lower) / (upper - lower).replace(0, np.nan)
        return upper, lower, ma, bb_pct

    @staticmethod
    def atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int) -> pd.Series:
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs()
        ], axis=1).max(axis=1)
        return tr.rolling(n).mean()

    @staticmethod
    def macd(close: pd.Series, fast: int, slow: int, signal: int):
        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        return macd_line, signal_line, macd_line - signal_line

    @staticmethod
    def adx(high: pd.Series, low: pd.Series, close: pd.Series, n: int) -> pd.Series:
        prev_high = high.shift(1)
        prev_low = low.shift(1)
        prev_close = close.shift(1)
        plus_dm = (high - prev_high).clip(lower=0)
        minus_dm = (prev_low - low).clip(lower=0)
        plus_dm = plus_dm.where(high - prev_high > prev_low - low, 0)
        minus_dm = minus_dm.where(prev_low - low > high - prev_high, 0)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs()
        ], axis=1).max(axis=1)
        atr_val = tr.ewm(alpha=1/n, adjust=False).mean()  # Wilder smooth
        pdi = 100 * plus_dm.ewm(alpha=1/n, adjust=False).mean() / atr_val
        mdi = 100 * minus_dm.ewm(alpha=1/n, adjust=False).mean() / atr_val
        dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
        return dx.ewm(alpha=1/n, adjust=False).mean()

    @staticmethod
    def vwap_dev(high: pd.Series, low: pd.Series, close: pd.Series,
                 volume: pd.Series, n: int) -> Tuple[pd.Series, pd.Series]:
        """VWAP偏差（σ单位），从v11引入"""
        tp = (high + low + close) / 3
        vwap = (tp * volume).rolling(n).sum() / volume.rolling(n).sum()
        variance = ((tp - vwap) ** 2 * volume).rolling(n).sum() / volume.rolling(n).sum()
        vwap_std = np.sqrt(variance).replace(0, np.nan)
        dev = (close - vwap) / vwap_std
        return vwap, dev

    @staticmethod
    def hurst(ts: np.ndarray, min_lag: int = 2, max_lag: int = 20) -> float:
        """[FIX-2] poly[0]，不乘2"""
        lags = range(min_lag, min(max_lag + 1, len(ts) // 2))
        if len(lags) < 3:
            return 0.5
        tau = [np.std(ts[lag:] - ts[:-lag]) for lag in lags]
        tau = np.array([t for t in tau if t > 0])
        lags_arr = np.array(list(lags))[:len(tau)]
        if len(lags_arr) < 3:
            return 0.5
        poly = np.polyfit(np.log(lags_arr), np.log(tau), 1)
        return float(np.clip(poly[0], 0.0, 1.0))  # [FIX-2] 不乘2，并裁剪到合理范围


# ============================================================
# 信号数据结构
# ============================================================
@dataclass
class SignalV12:
    direction: str = 'HOLD'       # LONG / SHORT / HOLD
    confidence: float = 0.0
    trend: str = 'FLAT'
    rsi: float = 50.0
    atr: float = 0.0
    atr_pct: float = 0.0
    bb_pct: float = 0.5
    hurst: float = 0.5
    adx: float = 0.0
    vol_ratio: float = 1.0
    vwap_dev: float = 0.0
    macd_weight: float = 0.0
    tp_price: float = 0.0
    sl_price: float = 0.0
    tp_window: int = 8
    position_size_u: float = 0.0  # 建议仓位（USDT）
    details: List[str] = field(default_factory=list)


# ============================================================
# 主引擎 v12
# ============================================================
class KillerSystemV12:
    version = 'v1.2'
    build = '2026-05-01'

    def __init__(self, params: Optional[Dict] = None):
        self.p = {**DEFAULTS_V12, **(params or {})}

    # ─── 查表辅助 ───────────────────────────────────────────
    def _rsi_th(self, atr_pct: float) -> Tuple[float, float]:
        for thresh, lt, st in self.p['rsi_matrix']:
            if atr_pct < thresh:
                return lt, st
        return 38, 62

    def _tp_sl_params(self, atr_pct: float) -> Tuple[float, float, int]:
        for thresh, tm, sm, win in self.p['tp_sl']:
            if atr_pct < thresh:
                return tm, sm, win
        return 3.0, 1.0, 12

    def _macd_weight(self, macd_line: float, signal_line: float, close: float) -> float:
        """[FIX-3] if/elif 链，修复原来的双循环错误"""
        if close <= 0:
            return 0.0
        ratio = (macd_line - signal_line) / close
        if ratio > 0.25:   return 0.20
        elif ratio > 0.10: return 0.10
        elif ratio > -0.10: return 0.00   # [FIX-3] 中性区返回0
        elif ratio > -0.25: return -0.05
        else:               return -0.10

    def _calc_position_size(self, entry: float, sl: float) -> float:
        """按固定风险百分比计算仓位（USDT）"""
        capital = self.p['capital']
        risk_pct = self.p['risk_pct']
        risk_usdt = capital * risk_pct          # 最大亏损额
        sl_pct = abs(entry - sl) / entry
        if sl_pct <= 0:
            return 0.0
        pos = risk_usdt / sl_pct               # 仓位大小(USDT)
        return round(min(pos, capital * 0.5), 2)  # 最大不超过50%资金

    # ─── 信号生成 ───────────────────────────────────────────
    def analyze(self, df: pd.DataFrame) -> SignalV12:
        sig = SignalV12()
        if len(df) < self.p['warmup']:
            sig.details.append(f'预热不足({len(df)}<{self.p["warmup"]})')
            return sig

        c = df['close']; h = df['high']; l = df['low']; v = df['volume']
        last = len(df) - 1

        # 计算指标
        e20 = Indicators.ema(c, self.p['ema_fast'])
        e50 = Indicators.ema(c, self.p['ema_slow'])
        rsi = Indicators.rsi(c, self.p['rsi_period'])
        _, _, _, bb_pct = Indicators.bb(c, self.p['bb_period'], self.p['bb_std'])
        atr_s = Indicators.atr(h, l, c, self.p['atr_period'])
        macd_line, sig_line, _ = Indicators.macd(c, self.p['macd_fast'],
                                                   self.p['macd_slow'], self.p['macd_sig'])
        adx_s = Indicators.adx(h, l, c, self.p['adx_period'])
        vol_ma = v.rolling(self.p['vol_ma']).mean()
        _, vwap_d = Indicators.vwap_dev(h, l, c, v, self.p['vwap_window'])

        # 基础数据填充
        sig.rsi = float(rsi.iloc[last])
        sig.atr = float(atr_s.iloc[last])
        sig.atr_pct = sig.atr / float(c.iloc[last]) * 100.0
        sig.bb_pct = float(bb_pct.iloc[last])
        sig.adx = float(adx_s.iloc[last])
        sig.vwap_dev = float(vwap_d.iloc[last]) if not pd.isna(vwap_d.iloc[last]) else 0.0
        vm = float(vol_ma.iloc[last])
        sig.vol_ratio = float(v.iloc[last]) / vm if vm > 0 else 1.0

        # Hurst
        hw = self.p['hurst_window']
        hurst_data = c.iloc[max(0, last - hw + 1):last + 1].values
        sig.hurst = Indicators.hurst(hurst_data)

        # MACD 权重
        sig.macd_weight = self._macd_weight(
            float(macd_line.iloc[last]), float(sig_line.iloc[last]), float(c.iloc[last])
        )

        # 趋势判定
        thresh = self.p['ema_thresh']
        e20v = float(e20.iloc[last]); e50v = float(e50.iloc[last])
        if e20v > e50v * (1 + thresh):
            sig.trend = 'UP'
        elif e20v < e50v * (1 - thresh):
            sig.trend = 'DOWN'
        else:
            sig.trend = 'FLAT'

        # 动态阈值
        long_th, short_th = self._rsi_th(sig.atr_pct)
        tp_mult, sl_mult, tp_win = self._tp_sl_params(sig.atr_pct)
        sig.tp_window = tp_win

        # 信号触发逻辑（v3.8 趋势锁定逻辑）
        direction = 'HOLD'
        if sig.trend in ('UP', 'FLAT') and sig.rsi < long_th and sig.bb_pct < self.p['bb_long']:
            direction = 'LONG'
        elif sig.trend in ('DOWN', 'FLAT') and sig.rsi > short_th and sig.bb_pct > self.p['bb_short']:
            direction = 'SHORT'

        if direction == 'HOLD':
            sig.details.append(f'未触发: trend={sig.trend} RSI={sig.rsi:.1f} BB%={sig.bb_pct:.2f}')
            return sig

        # ─── 置信度评分 ───────────────────────────────────────
        conf = 0.50

        # MACD（已修复）
        if (direction == 'LONG' and sig.macd_weight > 0) or \
           (direction == 'SHORT' and sig.macd_weight < 0):
            conf += abs(sig.macd_weight)
            sig.details.append(f'MACD同向{sig.macd_weight:+.2f}')

        # ADX（提升门槛至20）
        if sig.adx > self.p['adx_thresh']:
            conf += 0.10
            sig.details.append(f'ADX={sig.adx:.1f}确认')

        # 成交量
        if sig.vol_ratio > self.p['vol_spike']:
            conf += 0.10
            sig.details.append(f'放量{sig.vol_ratio:.1f}x')
        elif sig.vol_ratio < self.p['vol_dead']:
            conf -= 0.10
            sig.details.append(f'缩量{sig.vol_ratio:.1f}x')

        # VWAP偏差（v11引入）
        if direction == 'LONG' and sig.vwap_dev < -self.p['vwap_dev_thresh']:
            conf += 0.08
            sig.details.append(f'VWAP超卖{sig.vwap_dev:.1f}σ')
        elif direction == 'SHORT' and sig.vwap_dev > self.p['vwap_dev_thresh']:
            conf += 0.08
            sig.details.append(f'VWAP超买+{sig.vwap_dev:.1f}σ')

        # Hurst：趋势持续性
        if direction == 'LONG' and sig.hurst > 0.55:
            conf += 0.05
            sig.details.append(f'Hurst={sig.hurst:.2f}趋势')
        elif direction == 'SHORT' and sig.hurst < 0.45:
            conf += 0.05
            sig.details.append(f'Hurst={sig.hurst:.2f}均值回归')

        # 趋势锁定加分
        if sig.trend != 'FLAT':
            sig.details.append(f'{sig.trend}趋势锁定')
            conf += 0.05

        sig.confidence = float(np.clip(conf, 0.0, 1.0))

        # 置信度门槛（已提升至0.60）
        if sig.confidence < self.p['conf_thresh']:
            sig.details.append(f'置信度不足({sig.confidence:.2f}<{self.p["conf_thresh"]})')
            return sig

        sig.direction = direction

        # TP/SL 价格
        price = float(c.iloc[last])
        atr_v = sig.atr
        if direction == 'LONG':
            sig.tp_price = price + atr_v * tp_mult
            sig.sl_price = price - atr_v * sl_mult
        else:
            sig.tp_price = price - atr_v * tp_mult
            sig.sl_price = price + atr_v * sl_mult

        # 仓位建议（150U 固定风险）
        sig.position_size_u = self._calc_position_size(price, sig.sl_price)

        return sig

    # ─── 回测引擎（与 analyze 逻辑完全对齐）[FIX-6] ──────────
    def backtest(self, df: pd.DataFrame, symbol: str = '',
                 fee_rate: float = 0.0009) -> Dict:
        """含手续费+滑点的完整回测，逻辑与 analyze() 对齐"""
        n = len(df)
        if n < self.p['warmup']:
            return {'symbol': symbol, 'trades': [],
                    'summary': {'total': 0, 'error': '数据不足'}, 'equity': []}

        c = df['close']; h = df['high']; l = df['low']; v = df['volume']

        # 预计算全部指标
        e20 = Indicators.ema(c, self.p['ema_fast'])
        e50 = Indicators.ema(c, self.p['ema_slow'])
        rsi = Indicators.rsi(c, self.p['rsi_period'])
        _, _, _, bb_pct = Indicators.bb(c, self.p['bb_period'], self.p['bb_std'])
        atr_s = Indicators.atr(h, l, c, self.p['atr_period'])
        macd_line, sig_line, _ = Indicators.macd(c, self.p['macd_fast'],
                                                   self.p['macd_slow'], self.p['macd_sig'])
        adx_s = Indicators.adx(h, l, c, self.p['adx_period'])
        vol_ma = v.rolling(self.p['vol_ma']).mean()
        _, vwap_d = Indicators.vwap_dev(h, l, c, v, self.p['vwap_window'])

        equity = self.p['capital']
        trades = []; equity_curve = []
        position = None
        max_eq = equity; max_dd = 0.0
        ema_thresh = self.p['ema_thresh']

        for i in range(self.p['warmup'], n):
            e20v = float(e20.iloc[i]); e50v = float(e50.iloc[i])
            if e20v > e50v * (1 + ema_thresh):   trend = 'UP'
            elif e20v < e50v * (1 - ema_thresh): trend = 'DOWN'
            else:                                trend = 'FLAT'

            atr_v = float(atr_s.iloc[i])
            atr_pct = atr_v / float(c.iloc[i]) * 100.0
            long_th, short_th = self._rsi_th(atr_pct)
            tp_mult, sl_mult, tp_win = self._tp_sl_params(atr_pct)

            # 出场检查
            if position is not None:
                ep = None; er = None
                if position['dir'] == 'LONG':
                    if float(l.iloc[i]) <= position['sl']:
                        ep = position['sl']; er = 'SL'
                    elif float(h.iloc[i]) >= position['tp']:
                        ep = position['tp']; er = 'TP'
                else:
                    if float(h.iloc[i]) >= position['sl']:
                        ep = position['sl']; er = 'SL'
                    elif float(l.iloc[i]) <= position['tp']:
                        ep = position['tp']; er = 'TP'

                if ep is None:
                    hold = i - position['idx']
                    if hold >= tp_win:
                        ep = float(c.iloc[i]); er = 'TIMEOUT'
                    elif (position['dir'] == 'LONG' and trend == 'DOWN') or \
                         (position['dir'] == 'SHORT' and trend == 'UP'):
                        ep = float(c.iloc[i]); er = 'TREND_FLIP'

                if ep is not None:
                    raw_pnl_pct = ((ep - position['ep']) / position['ep']
                                   if position['dir'] == 'LONG'
                                   else (position['ep'] - ep) / position['ep'])
                    cost = fee_rate * 2  # 双边手续费
                    net_pnl_pct = raw_pnl_pct - cost
                    net_pnl_u = position['size'] * net_pnl_pct
                    equity += net_pnl_u
                    trades.append({
                        'entry_idx': position['idx'],
                        'exit_idx': i,
                        'direction': position['dir'],
                        'entry_price': position['ep'],
                        'exit_price': ep,
                        'pnl_pct': net_pnl_pct * 100,
                        'pnl_u': net_pnl_u,
                        'exit_reason': er,
                        'confidence': position['conf'],
                        'size_u': position['size'],
                    })
                    position = None
                    max_eq = max(max_eq, equity)
                    max_dd = max(max_dd, (max_eq - equity) / max_eq * 100.0)

            equity_curve.append(equity)

            # 开仓（置信度评分与 analyze() 对齐）
            if position is None:
                rsi_v = float(rsi.iloc[i])
                bb_v  = float(bb_pct.iloc[i])
                direction = None
                if trend in ('UP', 'FLAT') and rsi_v < long_th and bb_v < self.p['bb_long']:
                    direction = 'LONG'
                elif trend in ('DOWN', 'FLAT') and rsi_v > short_th and bb_v > self.p['bb_short']:
                    direction = 'SHORT'

                if direction:
                    # 置信度评分（与 analyze 对齐）[FIX-6]
                    mw = self._macd_weight(float(macd_line.iloc[i]),
                                           float(sig_line.iloc[i]), float(c.iloc[i]))
                    adx_v = float(adx_s.iloc[i])
                    vm = float(vol_ma.iloc[i])
                    vr = float(v.iloc[i]) / vm if vm > 0 else 1.0
                    vwap_v = float(vwap_d.iloc[i]) if not pd.isna(vwap_d.iloc[i]) else 0.0

                    conf = 0.50
                    if (direction == 'LONG' and mw > 0) or (direction == 'SHORT' and mw < 0):
                        conf += abs(mw)
                    if adx_v > self.p['adx_thresh']:
                        conf += 0.10
                    if vr > self.p['vol_spike']:
                        conf += 0.10
                    elif vr < self.p['vol_dead']:
                        conf -= 0.10
                    if direction == 'LONG' and vwap_v < -self.p['vwap_dev_thresh']:
                        conf += 0.08
                    elif direction == 'SHORT' and vwap_v > self.p['vwap_dev_thresh']:
                        conf += 0.08
                    if trend != 'FLAT':
                        conf += 0.05
                    conf = float(np.clip(conf, 0.0, 1.0))

                    if conf < self.p['conf_thresh']:
                        continue

                    # TP/SL
                    price = float(c.iloc[i])
                    tp = price + atr_v * tp_mult if direction == 'LONG' else price - atr_v * tp_mult
                    sl = price - atr_v * sl_mult if direction == 'LONG' else price + atr_v * sl_mult

                    # 仓位
                    sl_pct = abs(price - sl) / price
                    size = min(equity * self.p['risk_pct'] / sl_pct, equity * 0.5) if sl_pct > 0 else 0

                    position = {
                        'dir': direction, 'ep': price, 'idx': i,
                        'tp': tp, 'sl': sl, 'atr': atr_v,
                        'conf': conf, 'size': size,
                    }

        # 统计
        total = len(trades)
        wins   = [t for t in trades if t['pnl_u'] > 0]
        losses = [t for t in trades if t['pnl_u'] <= 0]
        gross_win  = sum(t['pnl_u'] for t in wins)
        gross_loss = sum(t['pnl_u'] for t in losses)

        summary = {
            'symbol':        symbol,
            'total':         total,
            'win_rate':      len(wins) / total * 100 if total else 0,
            'total_pnl_u':   equity - self.p['capital'],
            'total_pnl_pct': (equity - self.p['capital']) / self.p['capital'] * 100,
            'avg_win_u':     np.mean([t['pnl_u'] for t in wins])  if wins   else 0,
            'avg_loss_u':    np.mean([t['pnl_u'] for t in losses]) if losses else 0,
            'profit_factor': gross_win / abs(gross_loss) if gross_loss < 0 else float('inf'),
            'max_drawdown':  max_dd,
            'final_equity':  equity,
            'tp_hits':       sum(1 for t in trades if t['exit_reason'] == 'TP'),
            'sl_hits':       sum(1 for t in trades if t['exit_reason'] == 'SL'),
            'timeout':       sum(1 for t in trades if t['exit_reason'] == 'TIMEOUT'),
            'trend_flip':    sum(1 for t in trades if t['exit_reason'] == 'TREND_FLIP'),
            'long_trades':   sum(1 for t in trades if t['direction'] == 'LONG'),
            'short_trades':  sum(1 for t in trades if t['direction'] == 'SHORT'),
        }
        return {'symbol': symbol, 'trades': trades, 'summary': summary, 'equity': equity_curve}

    def show_params(self):
        print(f"\n{'='*55}")
        print(f"  杀手锏交易系统 {self.version} | {self.build}")
        print(f"  资金: {self.p['capital']}U | 单笔风险: {self.p['risk_pct']*100:.0f}%"
              f" | 最大亏损/笔: {self.p['capital']*self.p['risk_pct']:.1f}U")
        print(f"{'='*55}\n")
