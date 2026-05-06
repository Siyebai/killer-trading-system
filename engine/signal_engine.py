"""
模块2: 信号引擎
- 每根15m K线收盘后触发
- 计算 ADX / EMA200 / ATR
- 判断 SHORT / LONG 触发条件
- 输出: Signal 对象 (方向/入场价/SL/TP/置信度)
"""
import numpy as np
from dataclasses import dataclass
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from engine.ws_feeder import Kline


@dataclass
class Signal:
    direction: str        # "LONG" / "SHORT" / "NONE"
    symbol: str
    entry_price: float
    sl_price: float
    tp_price: float
    atr: float
    adx: float
    ema200: float
    reason: str           # 触发描述
    ts: int               # K线时间戳


class SignalEngine:
    """
    策略 v1.2 信号引擎
    SHORT: 连续n_short根上涨 + 累涨≥min_pct + ADX≥adx_min
    LONG:  连续n_long根下跌  + 累跌≥min_pct + ADX≥adx_min + close>EMA200
    """

    def __init__(
        self,
        symbol: str = "BTCUSDT",
        n_short: int = 6,
        n_long: int = 4,
        min_pct: float = 0.002,
        adx_min: float = 20.0,
        ema_period: int = 200,
        atr_period: int = 14,
        adx_period: int = 14,
        tp_mult_short: float = 1.0,
        sl_mult_short: float = 1.0,
        tp_mult_long: float = 0.8,
        sl_mult_long: float = 1.0,
    ):
        self.symbol = symbol
        self.n_short = n_short
        self.n_long = n_long
        self.min_pct = min_pct
        self.adx_min = adx_min
        self.ema_period = ema_period
        self.atr_period = atr_period
        self.adx_period = adx_period
        self.tp_mult_short = tp_mult_short
        self.sl_mult_short = sl_mult_short
        self.tp_mult_long = tp_mult_long
        self.sl_mult_long = sl_mult_long

        # EMA状态（增量更新）
        self._ema200: Optional[float] = None
        self._ema_alpha = 2.0 / (ema_period + 1)

    # ── 指标计算 ─────────────────────────────────

    @staticmethod
    def _calc_atr(bars: List["Kline"], n: int = 14) -> float:
        if len(bars) < n + 1:
            return 0.0
        h = np.array([b.high for b in bars])
        l = np.array([b.low for b in bars])
        c = np.array([b.close for b in bars])
        tr = np.maximum(h - l,
             np.maximum(np.abs(h - np.roll(c, 1)),
                        np.abs(l - np.roll(c, 1))))
        tr[0] = h[0] - l[0]
        atr = tr[-n:].mean()
        return float(atr)

    @staticmethod
    def _calc_adx(bars: List["Kline"], n: int = 14) -> float:
        if len(bars) < n * 2:
            return 0.0
        h = np.array([b.high for b in bars])
        l = np.array([b.low for b in bars])
        c = np.array([b.close for b in bars])
        tr = np.maximum(h - l,
             np.maximum(np.abs(h - np.roll(c, 1)),
                        np.abs(l - np.roll(c, 1))))
        tr[0] = h[0] - l[0]
        pdm = np.where((h - np.roll(h, 1) > np.roll(l, 1) - l) & (h - np.roll(h, 1) > 0),
                       h - np.roll(h, 1), 0.0)
        ndm = np.where((np.roll(l, 1) - l > h - np.roll(h, 1)) & (np.roll(l, 1) - l > 0),
                       np.roll(l, 1) - l, 0.0)
        pdm[0] = ndm[0] = 0.0
        a14 = np.zeros(len(tr)); a14[:n] = tr[:n].mean()
        p14 = np.zeros(len(tr)); p14[:n] = pdm[:n].mean()
        d14 = np.zeros(len(tr)); d14[:n] = ndm[:n].mean()
        for i in range(n, len(tr)):
            a14[i] = a14[i-1] * (n-1)/n + tr[i]/n
            p14[i] = p14[i-1] * (n-1)/n + pdm[i]/n
            d14[i] = d14[i-1] * (n-1)/n + ndm[i]/n
        with np.errstate(divide="ignore", invalid="ignore"):
            pdi = np.where(a14 > 0, 100 * p14 / a14, 0.0)
            ndi = np.where(a14 > 0, 100 * d14 / a14, 0.0)
            dx  = np.where((pdi + ndi) > 0, 100 * np.abs(pdi - ndi) / (pdi + ndi), 0.0)
        adx = np.zeros(len(dx)); adx[:n] = dx[:n].mean()
        for i in range(n, len(dx)):
            adx[i] = adx[i-1] * (n-1)/n + dx[i]/n
        return float(adx[-1])

    def _update_ema200(self, close: float) -> float:
        if self._ema200 is None:
            self._ema200 = close
        else:
            self._ema200 = close * self._ema_alpha + self._ema200 * (1 - self._ema_alpha)
        return self._ema200

    # ── 主入口 ────────────────────────────────────

    def evaluate(self, bars: List["Kline"]) -> Signal:
        """
        传入已收盘K线列表（最新在末尾），返回信号
        最少需要 max(n_short, n_long, ema_period) + 30 根
        """
        min_bars = max(self.n_short, self.n_long, self.ema_period) + 30
        if len(bars) < min_bars:
            return self._none_signal(bars[-1] if bars else None, "数据不足")

        # 增量更新EMA200（使用所有历史）
        for bar in bars:
            self._update_ema200(bar.close)

        last = bars[-1]
        close = last.close
        atr = self._calc_atr(bars, self.atr_period)
        adx = self._calc_adx(bars, self.adx_period)
        ema200 = self._ema200 or close

        if atr <= 0:
            return self._none_signal(last, "ATR为0")

        closes = [b.close for b in bars]

        # ── SHORT检测 ──────────────────────────
        if adx >= self.adx_min:
            recent_s = closes[-(self.n_short + 1):]  # n_short+1个收盘价
            moves_s = [recent_s[i] - recent_s[i-1] for i in range(1, len(recent_s))]
            cum_rise = (recent_s[-1] - recent_s[0]) / recent_s[0] if recent_s[0] > 0 else 0

            if all(m > 0 for m in moves_s) and cum_rise >= self.min_pct:
                sl_p = close + atr * self.sl_mult_short
                tp_p = close - atr * self.tp_mult_short
                return Signal(
                    direction="SHORT",
                    symbol=self.symbol,
                    entry_price=close,
                    sl_price=round(sl_p, 2),
                    tp_price=round(tp_p, 2),
                    atr=round(atr, 2),
                    adx=round(adx, 1),
                    ema200=round(ema200, 2),
                    reason=f"连续{self.n_short}涨 累涨{cum_rise*100:.2f}% ADX={adx:.1f}",
                    ts=last.ts,
                )

        # ── LONG检测 ───────────────────────────
        if adx >= self.adx_min and close > ema200:
            recent_l = closes[-(self.n_long + 1):]
            moves_l = [recent_l[i] - recent_l[i-1] for i in range(1, len(recent_l))]
            cum_fall = (recent_l[0] - recent_l[-1]) / recent_l[0] if recent_l[0] > 0 else 0

            if all(m < 0 for m in moves_l) and cum_fall >= self.min_pct:
                sl_p = close - atr * self.sl_mult_long
                tp_p = close + atr * self.tp_mult_long
                return Signal(
                    direction="LONG",
                    symbol=self.symbol,
                    entry_price=close,
                    sl_price=round(sl_p, 2),
                    tp_price=round(tp_p, 2),
                    atr=round(atr, 2),
                    adx=round(adx, 1),
                    ema200=round(ema200, 2),
                    reason=f"连续{self.n_long}跌 累跌{cum_fall*100:.2f}% ADX={adx:.1f} close>EMA200",
                    ts=last.ts,
                )

        reason_parts = []
        if adx < self.adx_min:
            reason_parts.append(f"ADX={adx:.1f}<{self.adx_min}")
        if close <= ema200:
            reason_parts.append(f"close≤EMA200({ema200:.0f})")
        return self._none_signal(last, " | ".join(reason_parts) or "无信号")

    def _none_signal(self, bar, reason: str) -> Signal:
        ts = bar.ts if bar else 0
        price = bar.close if bar else 0.0
        return Signal(
            direction="NONE",
            symbol=self.symbol,
            entry_price=price,
            sl_price=0.0, tp_price=0.0,
            atr=0.0, adx=0.0, ema200=self._ema200 or 0.0,
            reason=reason, ts=ts,
        )


if __name__ == "__main__":
    # 单元测试：用本地数据验证信号引擎
    import sys, json
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from engine.ws_feeder import Kline

    data_file = Path(__file__).parent.parent / "data" / "BTCUSDT_15m_180d.json"
    raw = json.load(open(data_file))
    data = raw if isinstance(raw, list) else raw.get("data", [])

    bars = []
    for row in data:
        if isinstance(row, (list, tuple)):
            bars.append(Kline(ts=int(row[0]), o=row[1], h=row[2], l=row[3], c=row[4], v=row[5], closed=True))
        else:
            bars.append(Kline(
                ts=int(row.get("ts", row.get("timestamp", row.get("open_time", row.get("openTime", 0))))),
                o=row.get("open", 0), h=row.get("high", 0),
                l=row.get("low", 0),  c=row.get("close", 0),
                v=row.get("volume", 0), closed=True
            ))

    engine = SignalEngine()
    signals = {"LONG": 0, "SHORT": 0, "NONE": 0}

    # 滑动窗口验证
    WINDOW = 250
    signal_list = []
    for i in range(WINDOW, len(bars)):
        window = bars[i-WINDOW:i+1]
        # 重置EMA（滑动重算）
        eng = SignalEngine()
        sig = eng.evaluate(window)
        signals[sig.direction] += 1
        if sig.direction != "NONE":
            signal_list.append(sig)

    print(f"信号统计: SHORT={signals['SHORT']} LONG={signals['LONG']} NONE={signals['NONE']}")
    print(f"总信号: {signals['SHORT']+signals['LONG']} / {len(bars)-WINDOW} 根K线")
    print(f"\n最近5个信号:")
    from datetime import datetime, timezone
    for s in signal_list[-5:]:
        ts_str = datetime.fromtimestamp(s.ts/1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        print(f"  [{ts_str}] {s.direction} entry={s.entry_price} SL={s.sl_price} TP={s.tp_price} | {s.reason}")
