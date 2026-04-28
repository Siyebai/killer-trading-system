#!/usr/bin/env python3
"""
增强版风控系统 - 更完善的风险管理
"""

import time
import json
from typing import Dict, Optional, List
from collections import deque

try:
    from scripts.logger_factory import get_logger
    logger = get_logger("advanced_risk")
except ImportError:
    import logging
    logger = logging.getLogger("advanced_risk")


class AdvancedRiskManager:
    """增强版风控管理器"""

    def __init__(self, config: Dict, initial_equity: float):
        self.config = config
        self.initial_equity = initial_equity

        # 风控参数
        self.max_drawdown = config.get('max_drawdown', 0.08)
        self.max_daily_loss = config.get('max_daily_loss', 0.025)
        self.max_position_pct = config.get('max_position_pct', 0.10)
        self.max_symbol_exposure = config.get('max_symbol_exposure_pct', 0.15)
        self.max_total_exposure = config.get('max_total_exposure_pct', 0.50)
        self.consecutive_loss_limit = config.get('consecutive_loss_limit', 5)

        # 熔断机制
        self.circuit_breaker_active = False
        self.circuit_breaker_cooldown = config.get('circuit_breaker_cooldown', 300)
        self.circuit_breaker_end_ts = 0

        # 统计信息
        self.daily_realized_pnl = 0.0
        self.daily_date = None
        self.consecutive_losses = 0
        self.total_trades = 0
        self.total_wins = 0

        # 历史记录
        self.pnl_history = deque(maxlen=1000)
        self.equity_history = deque(maxlen=100)
        self.drawdown_history = deque(maxlen=100)

        # 峰值权益
        self.peak_equity = initial_equity
        self.current_equity = initial_equity

        # 风险事件
        self.risk_events = deque(maxlen=100)

    def _check_daily_reset(self):
        """每日重置"""
        today = time.strftime('%Y-%m-%d')
        if self.daily_date != today:
            self.daily_date = today
            self.daily_realized_pnl = 0.0
            self.consecutive_losses = 0

    def approve_order(self, order: Dict, current_price: float, equity: float,
                     volatility: float = 0.01, atr: float = 0.0) -> Dict:
        """
        审批订单

        Args:
            order: 订单信息
            current_price: 当前价格
            equity: 当前权益
            volatility: 波动率
            atr: ATR

        Returns:
            审批结果
        """
        try:
            self._check_daily_reset()

            # 第一层防御：参数校验
            if equity <= 0 or current_price <= 0:
                logger.warning(f"风控参数异常：equity={equity}, price={current_price}，拒绝订单")
                return {
                    'approved': False,
                    'reason': 'invalid_parameters',
                    'message': '价格或权益参数异常'
                }

            # 第二层防御：除零保护
            initial_equity_safe = max(self.initial_equity, 0.01)

            # 检查熔断器
            if self.circuit_breaker_active:
                if time.time() < self.circuit_breaker_end_ts:
                    return {
                        'approved': False,
                        'reason': 'circuit_breaker_active',
                        'message': '熔断器已触发，暂停交易'
                    }
                else:
                    self.circuit_breaker_active = False
                    self.risk_events.append({
                        'type': 'circuit_breaker_reset',
                        'timestamp': time.time()
                    })

            # 检查连续亏损限制
            if self.consecutive_losses >= self.consecutive_loss_limit:
                return {
                    'approved': False,
                    'reason': 'consecutive_losses_limit',
                    'message': f'连续亏损{self.consecutive_losses}次，达到限制'
                }

            # 检查日亏损限额
            if self.daily_realized_pnl <= -self.max_daily_loss * initial_equity_safe:
            self.trigger_circuit_breaker()
            return {
                'approved': False,
                'reason': 'daily_loss_limit',
                'message': f'日亏损超过限额: {self.daily_realized_pnl:.2f}'
            }

        # 计算建议仓位
        qty = order.get('qty', 0)
        max_qty = equity * self.max_position_pct / current_price
        adjusted_qty = min(qty, max_qty)

        if adjusted_qty <= 0:
            return {
                'approved': False,
                'reason': 'invalid_quantity',
                'message': f'订单数量无效: {qty}'
            }

        # 检查预估亏损
        if atr > 0:
            estimated_loss = adjusted_qty * current_price * 1.2 * atr / current_price
            max_loss_per_trade = equity * 0.003  # 单笔最大亏损0.3%

            if estimated_loss > max_loss_per_trade:
                return {
                    'approved': False,
                    'reason': 'estimated_loss_exceeds',
                    'message': f'预估亏损{estimated_loss:.2f}超过限额{max_loss_per_trade:.2f}'
                }

        # 动态调整（根据波动率）
        if volatility > 0.02:  # 高波动时减仓
            adjusted_qty *= 0.7
        elif volatility < 0.005:  # 低波动时可适当加仓
            adjusted_qty *= 1.2

        adjusted_qty = max(adjusted_qty, 0.001)  # 最小仓位

        return {
            'approved': True,
            'adjusted_qty': adjusted_qty,
            'original_qty': qty,
            'reason': 'ok',
            'risk_checks': {
                'consecutive_losses': self.consecutive_losses,
                'daily_pnl': self.daily_realized_pnl,
                'volatility': volatility
            }
        }

    def record_trade(self, pnl: float, is_stop_loss: bool = False):
        """记录交易"""
        self._check_daily_reset()

        self.daily_realized_pnl += pnl
        self.total_trades += 1
        self.pnl_history.append(pnl)

        # 更新当前权益
        self.current_equity = self.initial_equity + self.daily_realized_pnl + sum(self.pnl_history)

        # 更新峰值权益
        if self.current_equity > self.peak_equity:
            self.peak_equity = self.current_equity

        # 计算回撤
        drawdown = (self.peak_equity - self.current_equity) / self.peak_equity
        self.drawdown_history.append(drawdown)

        # 检查止损
        if pnl <= 0:
            self.consecutive_losses += 1

            # 止损交易额外记录
            if is_stop_loss:
                self.risk_events.append({
                    'type': 'stop_loss_triggered',
                    'pnl': pnl,
                    'timestamp': time.time()
                })

            # 检查回撤限额
            if drawdown > self.max_drawdown:
                self.trigger_circuit_breaker()
                self.risk_events.append({
                    'type': 'max_drawdown_exceeded',
                    'drawdown': drawdown,
                    'timestamp': time.time()
                })
        else:
            self.consecutive_losses = 0
            self.total_wins += 1

    def trigger_circuit_breaker(self):
        """触发熔断器"""
        try:
            self.circuit_breaker_active = True
            self.circuit_breaker_end_ts = time.time() + self.circuit_breaker_cooldown

            self.risk_events.append({
                'type': 'circuit_breaker_triggered',
                'cooldown_seconds': self.circuit_breaker_cooldown,
                'timestamp': time.time()
            })
            logger.warning(f"熔断器已触发，冷却时间 {self.circuit_breaker_cooldown}秒")
        except Exception as e:
            logger.error(f"触发熔断器失败：{e}")

    def reset_circuit_breaker(self):
        """重置熔断器"""
        try:
            self.circuit_breaker_active = False
            self.circuit_breaker_end_ts = 0
            logger.info("熔断器已重置")
        except Exception as e:
            logger.error(f"重置熔断器失败：{e}")

        self.risk_events.append({
            'type': 'circuit_breaker_reset',
            'timestamp': time.time()
        })

    def get_current_risk_metrics(self) -> Dict:
        """获取当前风险指标"""
        current_drawdown = (self.peak_equity - self.current_equity) / self.peak_equity

        # 计算胜率
        win_rate = self.total_wins / self.total_trades if self.total_trades > 0 else 0

        # 计算夏普比率（简化版）
        if len(self.pnl_history) > 10:
            avg_pnl = sum(self.pnl_history) / len(self.pnl_history)
            std_pnl = (sum((x - avg_pnl) ** 2 for x in self.pnl_history) / len(self.pnl_history)) ** 0.5
            sharpe = (avg_pnl / std_pnl) * (365 ** 0.5) if std_pnl > 0 else 0
        else:
            sharpe = 0

        return {
            'current_equity': self.current_equity,
            'peak_equity': self.peak_equity,
            'current_drawdown': current_drawdown,
            'daily_pnl': self.daily_realized_pnl,
            'total_trades': self.total_trades,
            'win_rate': win_rate,
            'consecutive_losses': self.consecutive_losses,
            'sharpe_ratio': sharpe,
            'circuit_breaker_active': self.circuit_breaker_active,
            'circuit_breaker_end_ts': self.circuit_breaker_end_ts
        }

    def get_risk_events(self, limit: int = 10) -> List[Dict]:
        """获取风险事件"""
        return list(self.risk_events)[-limit:]

    def export_state(self) -> Dict:
        """导出状态（用于持久化）"""
        return {
            'daily_realized_pnl': self.daily_realized_pnl,
            'daily_date': self.daily_date,
            'consecutive_losses': self.consecutive_losses,
            'total_trades': self.total_trades,
            'total_wins': self.total_wins,
            'peak_equity': self.peak_equity,
            'current_equity': self.current_equity,
            'circuit_breaker_active': self.circuit_breaker_active,
            'circuit_breaker_end_ts': self.circuit_breaker_end_ts,
            'pnl_history': list(self.pnl_history),
            'drawdown_history': list(self.drawdown_history)
        }

    def load_state(self, state: Dict):
        """加载状态"""
        self.daily_realized_pnl = state.get('daily_realized_pnl', 0.0)
        self.daily_date = state.get('daily_date')
        self.consecutive_losses = state.get('consecutive_losses', 0)
        self.total_trades = state.get('total_trades', 0)
        self.total_wins = state.get('total_wins', 0)
        self.peak_equity = state.get('peak_equity', self.initial_equity)
        self.current_equity = state.get('current_equity', self.initial_equity)
        self.circuit_breaker_active = state.get('circuit_breaker_active', False)
        self.circuit_breaker_end_ts = state.get('circuit_breaker_end_ts', 0)

        # 恢复历史数据
        if 'pnl_history' in state:
            self.pnl_history.extend(state['pnl_history'])
        if 'drawdown_history' in state:
            self.drawdown_history.extend(state['drawdown_history'])
