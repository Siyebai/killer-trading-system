#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("run")
except ImportError:
    import logging
    logger = logging.getLogger("run")
"""
一体化高频多策略交易系统 - 增强版V2
集成状态管理、数据验证、增强策略、智能风控
"""

import asyncio
import time
import json
import uuid
import argparse
import signal
import sys
from typing import Dict, List, Optional
from collections import deque
import numpy as np

# 导入自定义模块
sys.path.insert(0, '/workspace/projects/trading-simulator/scripts')
from state_manager import StateManager
from validator import DataValidator
from strategy_engine import EnhancedStrategyEngine
from advanced_risk import AdvancedRiskManager
from order_flow import OrderFlowAnalyzer
from market_regime import MarketRegimeDetector, TREND, RANGE

# ================== 配置 ==================
TRADING_MODE = "paper"
INITIAL_CASH = 100000.0
SYMBOLS = ["BTCUSDT"]

# 多策略配置
MULTI_STRATEGY_CONFIG = {
    "signal_threshold": 0.6,
    "conflict_threshold": 0.2,
    "ma_trend": {"initial_weight": 0.3, "fast_window": 10, "slow_window": 30, "consecutive_loss_limit": 3, "cooldown_seconds": 1800},
    "rsi_mean_revert": {"initial_weight": 0.2, "rsi_oversold": 30, "rsi_overbought": 70, "consecutive_loss_limit": 2, "cooldown_seconds": 1200},
    "orderflow_break": {"initial_weight": 0.3, "imbalance_threshold": 0.3, "cvd_trend_threshold": 0.2, "consecutive_loss_limit": 2, "cooldown_seconds": 900},
    "volatility_break": {"initial_weight": 0.2, "atr_multiplier": 1.5, "consecutive_loss_limit": 3, "cooldown_seconds": 1800}
}

# 风控配置
RISK_CONFIG = {
    "max_drawdown": 0.08,
    "max_daily_loss": 0.025,
    "max_position_pct": 0.10,
    "max_symbol_exposure_pct": 0.15,
    "max_total_exposure_pct": 0.50,
    "consecutive_loss_limit": 5,
    "circuit_breaker_cooldown": 300
}

# ================== 日志系统 ==================
class TradingLogger:
    """交易日志系统"""

    def __init__(self, log_file: str = "trading.log"):
        self.log_file = log_file
        self.log_buffer = deque(maxlen=1000)

    def log(self, level: str, message: str):
        """记录日志"""
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"[{timestamp}] [{level}] {message}"
        logger.info(log_entry)
        self.log_buffer.append(log_entry)

        # 写入文件（异步）
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(log_entry + '\n')
        except Exception as e:
            logger.error(f"日志写入失败: {e}")

    def info(self, message: str):
        self.log("INFO", message)

    def warning(self, message: str):
        self.log("WARNING", message)

    def error(self, message: str):
        self.log("ERROR", message)

    def get_recent_logs(self, limit: int = 50) -> List[str]:
        return list(self.log_buffer)[-limit:]


# ================== 环形缓冲区 ==================
class RingBuffer:
    """高性能环形缓冲区"""
    __slots__ = ('size', 'data', 'index', 'count')

    def __init__(self, size: int):
        self.size = size
        self.data = np.zeros(size, dtype=np.float64)
        self.index = 0
        self.count = 0

    def append(self, value: float):
        self.data[self.index] = value
        self.index = (self.index + 1) % self.size
        self.count = min(self.count + 1, self.size)

    def all(self) -> np.ndarray:
        if self.count < self.size:
            return self.data[:self.count]
        return np.roll(self.data, -self.index)


# ================== 增量指标计算 ==================
class IncrementalIndicators:
    """增量指标计算器"""
    __slots__ = ('prices', 'volumes', 'highs', 'lows')

    def __init__(self, maxlen=200):
        self.prices = RingBuffer(maxlen)
        self.volumes = RingBuffer(maxlen)
        self.highs = RingBuffer(maxlen)
        self.lows = RingBuffer(maxlen)

    def update_bar(self, open_p, high, low, close, volume) -> Optional[Dict]:
        """更新K线并计算指标"""
        self.prices.append(close)
        self.volumes.append(volume)
        self.highs.append(high)
        self.lows.append(low)

        p = self.prices.all()
        n = len(p)

        if n < 5:
            return None

        # SMA
        sma5 = np.mean(p[-5:])
        sma20 = np.mean(p[-20:]) if n >= 20 else p[-1]

        # 波动率
        vol = np.std(np.diff(p[-20:]) / p[-21:-1]) if n >= 20 else 0.01

        # 成交量
        v = self.volumes.all()
        avg_vol = np.mean(v[-20:]) if n >= 20 else volume
        vol_surge = volume / (avg_vol + 1e-6)

        # RSI
        rsi = self._calc_rsi(p)

        # ATR
        atr = self._calc_atr()

        return {
            'close': close, 'sma5': sma5, 'sma20': sma20,
            'volatility': vol, 'volume_surge': vol_surge,
            'rsi': rsi, 'atr': atr
        }

    def _calc_rsi(self, prices: np.ndarray) -> float:
        n = len(prices)
        if n < 15:
            return 50.0
        deltas = np.diff(prices[-15:])
        gains = np.sum(deltas[deltas > 0])
        losses = -np.sum(deltas[deltas < 0])
        avg_gain = gains / 14.0
        avg_loss = losses / 14.0
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - 100.0 / (1.0 + rs)

    def _calc_atr(self) -> float:
        p = self.prices.all()
        h = self.highs.all()
        l = self.lows.all()
        n = len(p)
        if n < 15:
            return p[-1] * 0.0005 if n > 0 else 0.0
        tr = np.maximum(h[-14:] - l[-14:], np.abs(h[-14:] - p[-15:-1]))
        tr = np.maximum(tr, np.abs(l[-14:] - p[-15:-1]))
        return np.mean(tr)


# ================== 投资组合管理 ==================
class Portfolio:
    """投资组合管理"""
    __slots__ = ('initial_equity', 'cash', 'realized_pnl', 'positions', '_peak_equity')

    def __init__(self, initial_cash: float):
        self.initial_equity = initial_cash
        self.cash = initial_cash
        self.realized_pnl = 0.0
        self.positions = {}
        self._peak_equity = initial_cash

    @property
    def equity(self) -> float:
        return self.cash + self.realized_pnl

    def update_position(self, symbol: str, side: str, qty: float, price: float, fee: float) -> float:
        """更新持仓"""
        if side == "BUY":
            self.cash -= qty * price + fee
            if symbol not in self.positions:
                self.positions[symbol] = {'qty': 0.0, 'avg_price': 0.0}
            pos = self.positions[symbol]
            old_cost = pos['qty'] * pos['avg_price']
            new_cost = old_cost + qty * price
            pos['qty'] += qty
            if pos['qty'] != 0:
                pos['avg_price'] = new_cost / pos['qty']
            return 0.0
        else:
            if symbol in self.positions:
                pos = self.positions[symbol]
                close_qty = min(qty, pos['qty'])
                pnl = (price - pos['avg_price']) * close_qty - fee
                self.realized_pnl += pnl
                self.cash += close_qty * price - fee
                pos['qty'] -= close_qty
                if pos['qty'] <= 1e-10:
                    del self.positions[symbol]
                return pnl
        return 0.0

    def snapshot(self, current_prices=None) -> Dict:
        """获取快照"""
        unrealized = 0.0
        for sym, pos in self.positions.items():
            mark = current_prices.get(sym, pos['avg_price']) if current_prices else pos['avg_price']
            unrealized += (mark - pos['avg_price']) * pos['qty']
        equity = self.cash + self.realized_pnl + unrealized
        if equity > self._peak_equity:
            self._peak_equity = equity
        drawdown = (self._peak_equity - equity) / self._peak_equity if self._peak_equity > 0 else 0
        return {
            'equity': equity, 'cash': self.cash, 'realized_pnl': self.realized_pnl,
            'unrealized_pnl': unrealized, 'drawdown': drawdown,
            'num_positions': len(self.positions)
        }


# ================== 交易智能体 ==================
class TradingAgentV2:
    """增强版交易智能体"""

    def __init__(self):
        self.logger = TradingLogger()
        self.logger.info("=" * 60)
        self.logger.info("交易系统启动 - 增强版V2")
        self.logger.info("=" * 60)

        # 初始化核心组件
        self.state_manager = StateManager()
        self.validator = DataValidator()

        # 尝试恢复状态
        self._try_restore_state()

        # 初始化投资组合
        self.portfolio = Portfolio(INITIAL_CASH)

        # 初始化风控
        self.risk = AdvancedRiskManager(RISK_CONFIG, INITIAL_CASH)

        # 初始化策略引擎
        self.strategy_engine = EnhancedStrategyEngine(MULTI_STRATEGY_CONFIG)

        # 初始化市场组件
        self.kline_managers = {sym: IncrementalIndicators(200) for sym in SYMBOLS}
        self.orderflow = {sym: OrderFlowAnalyzer(50, 20) for sym in SYMBOLS}
        self.regime_detector = MarketRegimeDetector(config={})

        # 持仓管理
        self.open_positions = {}

        # 统计信息
        self.trade_count = 0
        self.start_time = time.time()
        self._equity_history = []
        self._recent_trades = []

        # 运行状态
        self._running = True

        # 信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _try_restore_state(self):
        """尝试恢复状态"""
        try:
            system_state = self.state_manager.load_system_state()
            if system_state:
                from time import strftime, localtime
                self.logger.info(f"恢复上次运行状态，上次保存时间: {strftime('%Y-%m-%d %H:%M:%S', localtime(system_state.get('last_saved', 0)))}")
        except Exception as e:
            self.logger.warning(f"状态恢复失败: {e}")

    def _signal_handler(self, signum, frame):
        """信号处理"""
        self.logger.info(f"收到信号 {signum}，准备停止...")
        self._running = False

    async def on_tick(self, tick: Dict):
        """处理行情数据"""
        sym = tick.get('symbol', '')
        if not sym:
            return

        # 数据验证
        is_valid, cleaned_tick, error = self.validator.validate_market_tick(tick)
        if not is_valid:
            self.logger.warning(f"行情数据无效: {error}")
            return

        # 更新订单流
        self.orderflow[sym].add_trade(
            cleaned_tick['price'],
            cleaned_tick.get('volume', 0.0),
            cleaned_tick.get('is_buyer_maker', False)
        )

        # 更新指标
        ind = self.kline_managers[sym].update_bar(
            cleaned_tick['price'],
            cleaned_tick.get('bid', cleaned_tick['price']),
            cleaned_tick.get('ask', cleaned_tick['price']),
            cleaned_tick['price'],
            cleaned_tick.get('volume', 0.0)
        )

        if ind is None:
            return

        # 验证指标
        is_valid, cleaned_ind, error = self.validator.validate_indicators(ind)
        if not is_valid:
            return

        # 获取订单流特征
        flow = self.orderflow[sym].get_features()

        # 识别市场状态
        regime_result = self.regime_detector.detect(cleaned_ind, flow, cleaned_tick)
        regime = regime_result.get('regime', 'NOISE')

        # 只在允许的市场状态交易
        if regime not in [TREND, RANGE]:
            return

        # 检查是否有持仓
        if sym in self.open_positions:
            return

        # 生成交易信号
        direction, strength, trigger_strategy, reason = self.strategy_engine.generate_final_signal(
            cleaned_ind, flow
        )

        if direction == 0 or strength < 0.65:
            return

        # 计算仓位
        atr_val = max(cleaned_ind.get('atr', cleaned_tick['price'] * 0.01), cleaned_tick['price'] * 0.001)
        qty = self.portfolio.cash * 0.002 / cleaned_tick['price']

        # 风控审批
        risk_decision = self.risk.approve_order(
            {'qty': qty, 'symbol': sym},
            cleaned_tick['price'],
            self.portfolio.equity,
            volatility=cleaned_ind.get('volatility', 0.01),
            atr=atr_val
        )

        if not risk_decision['approved']:
            self.logger.info(f"订单被风控拒绝: {risk_decision['message']}")
            return

        qty = risk_decision['adjusted_qty']

        # 创建订单
        if direction == 1:
            action = "BUY"
            stop_loss = cleaned_tick['price'] - 1.2 * atr_val
            take_profit = cleaned_tick['price'] + 1.0 * atr_val
        else:
            action = "SELL"
            stop_loss = cleaned_tick['price'] + 1.2 * atr_val
            take_profit = cleaned_tick['price'] - 1.0 * atr_val

        self.open_positions[sym] = {
            'side': action,
            'entry_price': cleaned_tick['price'],
            'qty': qty,
            'sl': stop_loss,
            'tp': take_profit,
            'entry_time': time.time(),
            'strategy_id': trigger_strategy
        }

        self.trade_count += 1
        self.logger.info(f"开仓 {sym} {action} {qty:.4f} @ {cleaned_tick['price']:.2f} | 触发: {trigger_strategy} | {reason}")

    async def check_positions(self):
        """检查持仓（止盈止损）"""
        now = time.time()
        for sym, pos in list(self.open_positions.items()):
            try:
                ind_manager = self.kline_managers[sym]
                current_price = ind_manager.prices.all()[-1] if ind_manager.prices.count > 0 else pos['entry_price']

                if pos['side'] == "BUY":
                    if current_price <= pos['sl']:
                        await self.close_position(sym, pos, current_price, "stop_loss")
                    elif current_price >= pos['tp']:
                        await self.close_position(sym, pos, current_price, "take_profit")
                else:
                    if current_price >= pos['sl']:
                        await self.close_position(sym, pos, current_price, "stop_loss")
                    elif current_price <= pos['tp']:
                        await self.close_position(sym, pos, current_price, "take_profit")

                # 超时平仓
                if now - pos['entry_time'] > 120 and sym in self.open_positions:
                    await self.close_position(sym, pos, current_price, "timeout")
            except Exception as e:
                self.logger.error(f"检查持仓失败 {sym}: {e}")

    async def close_position(self, sym: str, pos: Dict, price: float, reason: str):
        """平仓"""
        if sym not in self.open_positions:
            return

        close_side = "SELL" if pos['side'] == "BUY" else "BUY"

        if pos['side'] == "BUY":
            pnl = (price - pos['entry_price']) * pos['qty']
        else:
            pnl = (pos['entry_price'] - price) * pos['qty']

        fee = abs(pnl) * 0.0005
        self.portfolio.update_position(sym, close_side, pos['qty'], price, fee)

        is_stop = (reason == "stop_loss")
        self.risk.record_trade(pnl, is_stop_loss=is_stop)

        trade_result = {
            'pnl': pnl,
            'strategy_id': pos.get('strategy_id'),
            'timestamp': time.time()
        }
        self.strategy_engine.update_after_trade(trade_result)

        # 记录交易
        self.state_manager.save_trade(trade_result)

        self._equity_history.append(self.portfolio.snapshot()['equity'])
        self._recent_trades.append({
            'time': time.strftime("%H:%M:%S"),
            'side': pos['side'],
            'price': price,
            'pnl': pnl,
            'reason': reason
        })
        self._recent_trades = self._recent_trades[-50:]

        self.logger.info(f"平仓 {sym} {reason} | PnL: {pnl:.2f} | 胜率: {self.risk.get_current_risk_metrics()['win_rate']*100:.1f}%")

        del self.open_positions[sym]

    def get_dashboard_state(self) -> Dict:
        """获取仪表盘状态"""
        snap = self.portfolio.snapshot()
        risk_metrics = self.risk.get_current_risk_metrics()

        return {
            'equity': snap['equity'],
            'cash': snap['cash'],
            'realized_pnl': snap['realized_pnl'],
            'unrealized_pnl': snap['unrealized_pnl'],
            'drawdown': snap['drawdown'],
            'total_trades': self.trade_count,
            'win_rate': risk_metrics['win_rate'],
            'consecutive_losses': risk_metrics['consecutive_losses'],
            'num_positions': snap['num_positions'],
            'mode': TRADING_MODE,
            'uptime': f"{(time.time()-self.start_time)/60:.0f}m",
            'equity_history': self._equity_history[-100:],
            'recent_trades': self._recent_trades[-20:],
            'strategy_weights': self.strategy_engine.get_weights(),
            'risk_metrics': risk_metrics,
            'circuit_breaker': risk_metrics['circuit_breaker_active']
        }

    def save_state(self):
        """保存当前状态"""
        try:
            # 保存系统状态
            self.state_manager.save_system_state({
                'last_saved': time.time(),
                'trade_count': self.trade_count,
                'start_time': self.start_time
            })

            # 保存风控状态
            self.state_manager.save_risk_stats(self.risk.export_state())

            # 保存策略权重
            self.state_manager.save_strategy_weights(self.strategy_engine.get_weights())

            self.logger.info("状态已保存")
        except Exception as e:
            self.logger.error(f"状态保存失败: {e}")


# ================== 模拟行情 ==================
async def fetch_mock_tick(symbol: str):
    """生成模拟行情"""
    base_price = 50000.0
    while True:
        price = base_price + np.random.normal(0, base_price * 0.002)
        bid = price * 0.9998
        ask = price * 1.0002
        volume = np.random.uniform(0.5, 5.0)
        is_buyer_maker = np.random.choice([True, False])

        tick = {
            'symbol': symbol,
            'price': price,
            'volume': volume,
            'is_buyer_maker': is_buyer_maker,
            'bid': bid,
            'ask': ask,
            'timestamp': int(time.time())  # 秒级时间戳
        }

        yield tick
        await asyncio.sleep(0.5)


# ================== 简化仪表盘 ==================
class SimpleDashboard:
    """简化仪表盘"""
    def __init__(self, agent: TradingAgentV2):
        self.agent = agent
        self._running = True

    async def run(self):
        """运行仪表盘"""
        self.agent.logger.info("仪表盘启动")
        while self._running:
            state = self.agent.get_dashboard_state()
            logger.info(f"\n[{time.strftime('%H:%M:%S')}] 状态:")
            logger.info(f"  资金: ${state['equity']:.2f} | 现金: ${state['cash']:.2f}")
            logger.info(f"  盈亏: ${state['realized_pnl']:.2f} | 回撤: {state['drawdown']*100:.2f}%")
            logger.info(f"  交易: {state['total_trades']} | 胜率: {state['win_rate']*100:.1f}%")
            logger.info(f"  连亏: {state['consecutive_losses']} | 持仓: {state['num_positions']}")
            logger.info(f"  权重: {state['strategy_weights']}")

            if state['circuit_breaker']:
                logger.info(f"  ⚠️ 熔断器已激活")

            await asyncio.sleep(1)

    def stop(self):
        self._running = False


# ================== 主入口 ==================
async def main():
    """主函数"""
    agent = TradingAgentV2()
    dashboard = SimpleDashboard(agent)

    # 定期保存状态
    async def periodic_save():
        while agent._running:
            await asyncio.sleep(60)  # 每分钟保存一次
            agent.save_state()

    # 启动任务
    save_task = asyncio.create_task(periodic_save())
    dashboard_task = asyncio.create_task(dashboard.run())

    try:
        # 启动交易循环
        for sym in SYMBOLS:
            async for tick in fetch_mock_tick(sym):
                if not agent._running:
                    break

                await agent.on_tick(tick)
                await agent.check_positions()

    except KeyboardInterrupt:
        agent.logger.info("收到中断信号")
    except Exception as e:
        agent.logger.error(f"运行错误: {e}")
    finally:
        # 清理
        agent._running = False
        dashboard.stop()
        agent.save_state()

        await asyncio.sleep(0.5)
        agent.logger.info("=" * 60)
        agent.logger.info("系统已停止")
        agent.logger.info("=" * 60)

        # 打印最终统计
        state = agent.get_dashboard_state()
        agent.logger.info(f"最终资金: ${state['equity']:.2f}")
        agent.logger.info(f"总交易: {state['total_trades']}")
        agent.logger.info(f"胜率: {state['win_rate']*100:.1f}%")
        agent.logger.info(f"总盈亏: ${state['realized_pnl']:.2f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="一体化高频交易系统 V2")
    parser.add_argument("--mode", default="simple", choices=["simple"],
                       help="运行模式")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("一体化高频多策略交易系统 V2")
    logger.info("=" * 60)
    logger.info("按 Ctrl+C 停止系统")
    logger.info("=" * 60)

    asyncio.run(main())
