#!/usr/bin/env python3
"""
增强版策略引擎 - 完整的策略管理和信号生成
"""

import time
import numpy as np
from typing import Dict, List, Tuple, Optional
from collections import deque

# 导入日志
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("strategy_engine")
except ImportError:
    import logging
    logger = logging.getLogger("strategy_engine")

# 导入事件总线（Phase 5.6新增）
try:
    from scripts.event_bus import get_event_bus
    EVENT_BUS_AVAILABLE = True
except ImportError:
    EVENT_BUS_AVAILABLE = False


class BaseStrategy:
    """策略基类"""

    def __init__(self, strategy_id: str, config: Dict):
        self.strategy_id = strategy_id
        self.config = config
        self.enabled = True
        self.consecutive_losses = 0
        self.total_trades = 0
        self.win_rate = 0.0
        self.weight = config.get('initial_weight', 0.25)
        self.cooldown_end_ts = 0
        self.pnl_history = deque(maxlen=100)
        self.last_signal = None

    def generate_signal(self, indicators: Dict, orderflow: Dict) -> Tuple[int, float, str]:
        """
        生成交易信号

        Returns:
            (方向, 强度, 原因)
        """
        raise NotImplementedError

    def update_status(self, pnl: float):
        """更新策略状态"""
        self.total_trades += 1
        self.pnl_history.append(pnl)

        if pnl > 0:
            self.consecutive_losses = 0
            self.win_rate = (self.win_rate * (self.total_trades - 1) + 1) / self.total_trades
        else:
            self.consecutive_losses += 1
            self.win_rate = (self.win_rate * (self.total_trades - 1)) / self.total_trades

            # 连续亏损检查
            limit = self.config.get('consecutive_loss_limit', 3)
            if self.consecutive_losses >= limit:
                self.enabled = False
                self.cooldown_end_ts = int(time.time()) + self.config.get('cooldown_seconds', 1800)

    def check_enabled(self, now_ts: int) -> bool:
        """检查策略是否可用"""
        if not self.enabled and now_ts >= self.cooldown_end_ts:
            self.enabled = True
            self.consecutive_losses = 0
        return self.enabled

    def get_expected_return(self) -> float:
        """获取预期收益"""
        if not self.pnl_history:
            return 0.0
        return np.mean(self.pnl_history)


class MATrendStrategy(BaseStrategy):
    """移动平均线趋势策略"""

    def __init__(self, config: Dict):
        super().__init__("ma_trend", config)
        self.fast_period = config.get('fast_window', 10)
        self.slow_period = config.get('slow_window', 30)
        self.ma_cross_history = deque(maxlen=20)

    def generate_signal(self, indicators: Dict, orderflow: Dict) -> Tuple[int, float, str]:
        ma_fast = indicators.get('sma5', 0)
        ma_slow = indicators.get('sma20', 0)

        if ma_slow == 0:
            return 0, 0.0, "数据不足"

        # 计算MA比率
        ma_ratio = (ma_fast - ma_slow) / ma_slow

        # 检测金叉
        cross_signal = 0
        if len(self.ma_cross_history) >= 2:
            prev_ratio = self.ma_cross_history[-1]
            if prev_ratio <= 0 and ma_ratio > 0:
                cross_signal = 1  # 金叉
            elif prev_ratio >= 0 and ma_ratio < 0:
                cross_signal = -1  # 死叉

        self.ma_cross_history.append(ma_ratio)

        # 生成信号
        if ma_ratio > 0.002:  # 强上升趋势
            strength = min(abs(ma_ratio) * 100, 1.0)
            if cross_signal == 1:
                return 1, min(strength * 1.2, 1.0), f"MA金叉, 趋势强度={ma_ratio*100:.3f}%"
            return 1, strength, f"上升趋势, MA比率={ma_ratio*100:.3f}%"

        elif ma_ratio < -0.002:  # 强下降趋势
            strength = min(abs(ma_ratio) * 100, 1.0)
            if cross_signal == -1:
                return -1, min(strength * 1.2, 1.0), f"MA死叉, 趋势强度={ma_ratio*100:.3f}%"
            return -1, strength, f"下降趋势, MA比率={ma_ratio*100:.3f}%"

        return 0, 0.0, "趋势不明显"


class RSIMeanRevertStrategy(BaseStrategy):
    """RSI均值回归策略"""

    def __init__(self, config: Dict):
        super().__init__("rsi_mean_revert", config)
        self.oversold = config.get('rsi_oversold', 30)
        self.overbought = config.get('rsi_overbought', 70)
        self.rsi_history = deque(maxlen=20)

    def generate_signal(self, indicators: Dict, orderflow: Dict) -> Tuple[int, float, str]:
        rsi = indicators.get('rsi', 50)
        self.rsi_history.append(rsi)

        if len(self.rsi_history) < 2:
            return 0, 0.0, "数据不足"

        prev_rsi = self.rsi_history[-2]

        # 检测RSI反转
        if rsi <= self.oversold and prev_rsi > self.oversold:
            strength = min((self.oversold - rsi) / 20, 1.0)
            return 1, strength, f"RSI超卖反转, RSI={rsi:.2f}"

        elif rsi >= self.overbought and prev_rsi < self.overbought:
            strength = min((rsi - self.overbought) / 20, 1.0)
            return -1, strength, f"RSI超买反转, RSI={rsi:.2f}"

        # 极值信号
        elif rsi < self.oversold * 0.8:  # 严重超卖
            strength = min((self.oversold - rsi) / 15, 1.0)
            return 1, strength * 0.8, f"RSI严重超卖, RSI={rsi:.2f}"

        elif rsi > self.overbought * 1.1:  # 严重超买
            strength = min((rsi - self.overbought) / 15, 1.0)
            return -1, strength * 0.8, f"RSI严重超买, RSI={rsi:.2f}"

        return 0, 0.0, "RSI处于中性区域"


class OrderflowBreakStrategy(BaseStrategy):
    """订单流突破策略"""

    def __init__(self, config: Dict):
        super().__init__("orderflow_break", config)
        self.imbalance_th = config.get('imbalance_threshold', 0.3)
        self.cvd_th = config.get('cvd_trend_threshold', 0.2)

    def generate_signal(self, indicators: Dict, orderflow: Dict) -> Tuple[int, float, str]:
        imb = orderflow.get('imbalance', 0)
        cvd_trend = orderflow.get('cvd_slope', 0)
        pressure = orderflow.get('pressure', 0)

        # 买方主导
        if imb > self.imbalance_th and cvd_trend > self.cvd_th and pressure > 0.2:
            strength = min(imb * 2, 1.0)
            return 1, strength, f"买方主导, 不平衡={imb:.3f}, CVD斜率={cvd_trend:.3f}"

        # 卖方主导
        elif imb < -self.imbalance_th and cvd_trend < -self.cvd_th and pressure < -0.2:
            strength = min(abs(imb) * 2, 1.0)
            return -1, strength, f"卖方主导, 不平衡={imb:.3f}, CVD斜率={cvd_trend:.3f}"

        return 0, 0.0, "订单流平衡"


class VolatilityBreakStrategy(BaseStrategy):
    """波动率突破策略"""

    def __init__(self, config: Dict):
        super().__init__("volatility_break", config)
        self.atr_mult = config.get('atr_multiplier', 1.5)

    def generate_signal(self, indicators: Dict, orderflow: Dict) -> Tuple[int, float, str]:
        price = indicators.get('close', 0)
        atr = indicators.get('atr', price * 0.01)
        volatility = indicators.get('volatility', 0.01)

        # 波动率过高时不交易
        if volatility > 0.03:
            return 0, 0.0, f"波动率过高: {volatility*100:.2f}%"

        # 计算布林带
        sma20 = indicators.get('sma20', price)
        upper_band = sma20 + self.atr_mult * atr
        lower_band = sma20 - self.atr_mult * atr

        # 突破上轨
        if price > upper_band and atr > 0:
            strength = min((price - upper_band) / atr, 1.0)
            return 1, strength, f"突破上轨, 价格={price:.2f}, 上轨={upper_band:.2f}"

        # 突破下轨
        elif price < lower_band and atr > 0:
            strength = min((lower_band - price) / atr, 1.0)
            return -1, strength, f"突破下轨, 价格={price:.2f}, 下轨={lower_band:.2f}"

        return 0, 0.0, "价格在布林带内"


class EnhancedStrategyEngine:
    """增强版策略引擎"""

    def __init__(self, config: Dict):
        self.config = config
        self.signal_threshold = config.get('signal_threshold', 0.6)
        self.conflict_threshold = config.get('conflict_threshold', 0.2)

        # 初始化策略
        self.strategies: List[BaseStrategy] = [
            MATrendStrategy(config.get('ma_trend', {})),
            RSIMeanRevertStrategy(config.get('rsi_mean_revert', {})),
            OrderflowBreakStrategy(config.get('orderflow_break', {})),
            VolatilityBreakStrategy(config.get('volatility_break', {}))
        ]

        # 归一化权重
        total_weight = sum(s.weight for s in self.strategies)
        for s in self.strategies:
            s.weight /= total_weight

    def generate_final_signal(self, indicators: Dict, orderflow: Dict) -> Tuple[int, float, str, str]:
        """
        生成最终交易信号

        Returns:
            (方向, 强度, 触发策略, 原因)
        """
        now_ts = int(time.time())
        signals = []
        total_weight = 0.0
        strategy_status = []

        # 收集所有策略信号
        for strategy in self.strategies:
            is_enabled = strategy.check_enabled(now_ts)
            strategy_status.append({
                'strategy_id': strategy.strategy_id,
                'enabled': is_enabled,
                'weight': strategy.weight,
                'consecutive_losses': strategy.consecutive_losses
            })

            if not is_enabled:
                continue

            direction, strength, reason = strategy.generate_signal(indicators, orderflow)

            if direction != 0 and strength > 0.01:
                signals.append({
                    'direction': direction,
                    'strength': strength * strategy.weight,
                    'strategy_id': strategy.strategy_id,
                    'reason': reason
                })
                total_weight += strategy.weight

        # 广播signal.generated事件（Phase 5.6新增）
        if EVENT_BUS_AVAILABLE:
            self._publish_signal_generated_event(signals, strategy_status, total_weight)

        if not signals or total_weight == 0:
            return 0, 0.0, "", "无有效信号"

        # 计算多空得分
        long_score = sum(s['strength'] for s in signals if s['direction'] == 1) / total_weight
        short_score = sum(s['strength'] for s in signals if s['direction'] == -1) / total_weight

        # 冲突检测
        if abs(long_score - short_score) < self.conflict_threshold:
            return 0, 0.0, "", f"信号冲突: 多={long_score:.3f}, 空={short_score:.3f}"

        # 生成最终信号
        if long_score > short_score and long_score >= self.signal_threshold:
            # 选择最强的做多信号
            trigger = max([s for s in signals if s['direction'] == 1], key=lambda x: x['strength'])
            return 1, long_score, trigger['strategy_id'], trigger['reason']

        elif short_score > long_score and short_score >= self.signal_threshold:
            # 选择最强的做空信号
            trigger = max([s for s in signals if s['direction'] == -1], key=lambda x: x['strength'])
            return -1, short_score, trigger['strategy_id'], trigger['reason']

        return 0, 0.0, "", f"信号强度不足: 多={long_score:.3f}, 空={short_score:.3f}"

    def _publish_signal_generated_event(self, signals: List[Dict], strategy_status: List[Dict], total_weight: float):
        """
        广播信号生成事件（Phase 5.6新增）

        Args:
            signals: 信号列表
            strategy_status: 策略状态列表
            total_weight: 总权重
        """
        try:
            event_bus = get_event_bus()
            event_bus.publish(
                "signal.generated",
                {
                    "signal_count": len(signals),
                    "total_weight": total_weight,
                    "active_strategies": sum(1 for s in strategy_status if s['enabled']),
                    "total_strategies": len(strategy_status),
                    "strategy_status": strategy_status,
                    "signals_summary": {
                        "long_count": sum(1 for s in signals if s['direction'] == 1),
                        "short_count": sum(1 for s in signals if s['direction'] == -1),
                        "avg_strength": np.mean([s['strength'] for s in signals]) if signals else 0
                    }
                },
                source="strategy_engine"
            )
            logger.debug(f"信号生成事件已广播: {len(signals)}个信号")
        except Exception as e:
            logger.error(f"信号生成事件广播失败: {e}")

    def update_after_trade(self, trade_result: Dict):
        """交易后更新策略"""
        strategy_id = trade_result.get('strategy_id')
        if not strategy_id:
            return

        pnl = trade_result.get('pnl', 0.0)

        for strategy in self.strategies:
            if strategy.strategy_id == strategy_id:
                strategy.update_status(pnl)

                # 动态调整权重（基于历史表现）
                expected_return = strategy.get_expected_return()
                if expected_return != 0:
                    new_weight = strategy.weight * (1 + min(0.3, max(-0.3, expected_return * 0.01)))
                    strategy.weight = max(0.05, min(0.8, new_weight))
                break

        # 重新归一化
        total_weight = sum(s.weight for s in self.strategies)
        for s in self.strategies:
            s.weight /= total_weight

    def get_weights(self) -> Dict[str, float]:
        """获取策略权重"""
        return {s.strategy_id: s.weight for s in self.strategies}

    def get_strategy_stats(self) -> List[Dict]:
        """获取策略统计"""
        stats = []
        for s in self.strategies:
            stats.append({
                'strategy_id': s.strategy_id,
                'enabled': s.enabled,
                'weight': s.weight,
                'total_trades': s.total_trades,
                'win_rate': s.win_rate,
                'consecutive_losses': s.consecutive_losses,
                'expected_return': s.get_expected_return()
            })
        return stats
