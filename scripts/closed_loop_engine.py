#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
杀手锏交易系统 v5.3 - 闭环集成引擎
Phase B工程转化：将所有独立模块串联为闭环Pipeline

架构：
  DataPipeline → SignalPipeline → StrategyOrchestrator → PortfolioAllocator → RiskManager → FeedbackLoop

闭环流程：
  1. 数据获取+验证 → 2. 信号生成+确认流水线 → 3. 策略编排+自适应权重
  → 4. HRP+凯利资金分配 → 5. 风控熔断 → 6. 表现追踪+贝叶斯优化+权重调整

理论依据：
  - MLOps闭环架构：训练→部署→监控→反馈→重新训练
  - 信号到资产孵化体系：信号池→引擎→孵化→筛选→资产注册
  - 自适应策略权重：根据近期表现动态调整
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import argparse
import json
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('ClosedLoopEngine')


# ==================== 1. 信号确认流水线 ====================

class SignalConfirmationPipeline:
    """
    多级信号确认流水线
    理论：Hawkes+因果因子+多维评分的三级确认
    信号必须通过至少2级确认才被接受
    """
    
    def __init__(self, config=None):
        default_config = {
            'min_confirmations': 3,
            'weights': {
                'multidim_score': 0.40,
                'hurst_filter': 0.30,
                'volume_filter': 0.15,
                'momentum_confirm': 0.15
            },
            'threshold': 0.55
        }
        if config:
            default_config.update(config)
        self.config = default_config
        self.confirmation_log = []
    
    def confirm_signal(self, signal_type: int, data: Dict, strategy_type: str = 'mean_reversion') -> Dict:
        """
        多级信号确认（评分制，区分策略类型）
        
        Level 1: 策略感知评分 (权重40%)
          - 均值回归: RSI+BB为主
          - 趋势跟踪: MACD+ADX为主
        Level 2: Hurst指数确认 (权重30%)
        Level 3: 量比+动量确认 (权重30%)
        """
        scores = {}
        rsi = data.get('rsi', 50)
        bb_position = data.get('bb_position', 0.5)
        adx = data.get('adx', 20)
        macd_signal = data.get('macd_signal', 0)

        # Level 1: 策略感知评分
        if strategy_type in ('trend_following', 'trend'):
            scores['multidim'] = self._score_trend_signal(signal_type, rsi, adx, macd_signal, bb_position, data)
        else:
            scores['multidim'] = self._score_mean_reversion_signal(signal_type, rsi, adx, macd_signal, bb_position)

        confirmations = 1 if scores['multidim'] >= 0.3 else 0

        # Level 2: Hurst指数确认
        scores['hurst'] = self._score_hurst_signal(signal_type, data.get('hurst', 0.5), rsi, macd_signal)
        if scores['hurst'] >= 0.4:
            confirmations += 1

        # Level 3: 量比+动量确认
        scores['volume'], scores['momentum'] = self._score_volume_momentum(signal_type, data)
        if scores['volume'] >= 0.5 or scores['momentum'] >= 0.5:
            confirmations += 1

        # 加权总分
        total_score = (
            scores.get('multidim', 0) * 0.40 +
            scores.get('hurst', 0) * 0.30 +
            scores.get('volume', 0) * 0.15 +
            scores.get('momentum', 0) * 0.15
        )
        
        confirmed = confirmations >= self.config['min_confirmations'] and total_score >= self.config['threshold']
        
        result = {
            'signal_type': signal_type,
            'confirmations': confirmations,
            'total_score': total_score,
            'confirmed': confirmed,
            'scores': scores,
            'timestamp': datetime.now().isoformat()
        }
        
        self.confirmation_log.append(result)
        return result

    def _score_trend_signal(self, signal_type: int, rsi: float, adx: float, macd_signal: int, bb_position: float, data: Dict) -> float:
        """趋势跟踪信号评分: LONG=信号1, SHORT=信号-1"""
        if signal_type == 0:
            return 0.0
        is_long = signal_type == 1
        score = 0.0
        if is_long:
            if macd_signal == 1: score += 0.35
            if adx > 20: score += 0.30
            elif adx > 15: score += 0.15
            if rsi < 55: score += 0.15
            if bb_position < 0.6: score += 0.10
            if data.get('plus_di', 0) > data.get('minus_di', 0): score += 0.10
        else:
            if macd_signal == -1: score += 0.35
            if adx > 20: score += 0.30
            elif adx > 15: score += 0.15
            if rsi > 45: score += 0.15
            if bb_position > 0.4: score += 0.10
            if data.get('minus_di', 0) > data.get('plus_di', 0): score += 0.10
        return score

    def _score_mean_reversion_signal(self, signal_type: int, rsi: float, adx: float, macd_signal: int, bb_position: float) -> float:
        """均值回归信号评分: LONG=信号1, SHORT=信号-1"""
        if signal_type == 0:
            return 0.0
        is_long = signal_type == 1
        score = 0.0
        if is_long:
            if rsi < 40: score += 0.3
            elif rsi < 50: score += 0.15
            if bb_position < 0.3: score += 0.3
            elif bb_position < 0.5: score += 0.15
            if adx > 20: score += 0.2
            if macd_signal == 1: score += 0.2
        else:
            if rsi > 60: score += 0.3
            elif rsi > 50: score += 0.15
            if bb_position > 0.7: score += 0.3
            elif bb_position > 0.5: score += 0.15
            if adx > 20: score += 0.2
            if macd_signal == -1: score += 0.2
        return score

    def _score_hurst_signal(self, signal_type: int, hurst: float, rsi: float, macd_signal: int) -> float:
        """Hurst指数确认评分"""
        if signal_type == 0:
            return 0.0
        is_mean_rev = (signal_type == 1 and rsi < 40) or (signal_type == -1 and rsi > 60)
        is_trend = (signal_type == 1 and macd_signal == 1) or (signal_type == -1 and macd_signal == -1)
        if is_mean_rev and hurst < 0.5:
            return 1.0 - hurst
        elif is_trend and hurst > 0.5:
            return hurst
        return 0.2  # 部分确认：降低默认分，过滤低质量信号

    def _score_volume_momentum(self, signal_type: int, data: Dict) -> Tuple[float, float]:
        """量比+动量评分"""
        vol_ratio = data.get('vol_ratio', 1.0)
        momentum = data.get('momentum', 0)
        vol_score = 0.7 if vol_ratio > 0.8 else 0.3
        mom_score = 0.7 if ((momentum > -0.01 and signal_type == 1) or (momentum < 0.01 and signal_type == -1)) else 0.3
        return vol_score, mom_score


# ==================== 2. 自适应策略权重 ====================

class AdaptiveStrategyWeights:
    """
    自适应策略权重调整器
    理论：根据近期表现动态调整策略权重，表现好的策略增加权重，表现差的降低
    使用指数加权移动平均(EWMA)追踪策略表现
    """
    
    def __init__(self, n_strategies: int = 3, decay: float = 0.95):
        self.n_strategies = max(1, n_strategies)
        self.decay = decay  # EWMA衰减因子
        self.strategy_names = ['mean_reversion', 'trend_following', 'funding_rate']
        self.performance = {name: {'win_rate': 0.5, 'sharpe': 0.0, 'n_trades': 0} for name in self.strategy_names}
        self.weights = np.array([1.0 / self.n_strategies] * self.n_strategies)
        self.min_weight = 0.10  # 单策略最低权重10%
        self.max_weight = 0.60  # 单策略最高权重60%
        self.min_trades_for_eval = 10  # 最少交易数才参与权重调整
    
    def update_performance(self, strategy_name: str, trade_result: Dict):
        """更新策略表现追踪"""
        if strategy_name not in self.performance:
            return
        
        perf = self.performance[strategy_name]
        alpha = 1 - self.decay
        
        # EWMA更新胜率
        is_win = trade_result.get('pnl', 0) > 0
        perf['win_rate'] = self.decay * perf['win_rate'] + alpha * (1.0 if is_win else 0.0)
        
        # EWMA更新Sharpe
        pnl = trade_result.get('pnl', 0)
        perf['sharpe'] = self.decay * perf['sharpe'] + alpha * pnl
        perf['n_trades'] += 1
    
    def adjust_weights(self) -> np.ndarray:
        """
        根据近期表现调整策略权重
        使用softmax归一化确保权重和为1
        修复: 无交易策略不参与权重竞争
        """
        # 计算每个策略的综合得分
        scores = np.array([
            self.performance[name]['win_rate'] * 0.6 + 
            max(0, self.performance[name]['sharpe']) * 0.4
            for name in self.strategy_names
        ])
        
        # 关键修复: 无交易策略(n_trades==0)设为极低得分，不参与权重竞争
        active_mask = np.array([self.performance[name]['n_trades'] >= self.min_trades_for_eval 
                               for name in self.strategy_names])
        if not active_mask.any():
            return self.weights  # 没有任何策略有足够交易，保持初始权重
        
        # 无交易策略得分设为0.01（极低），确保权重向有交易策略倾斜
        for i in range(len(scores)):
            if not active_mask[i]:
                scores[i] = 0.01
        
        # 胜率差异放大：表现好的策略得分加倍
        max_wr = max(self.performance[n]['win_rate'] for n in self.strategy_names if self.performance[n]['n_trades'] > 0)
        for i, name in enumerate(self.strategy_names):
            if not active_mask[i]:
                continue
            wr_diff = max_wr - self.performance[name]['win_rate']
            if wr_diff > 0.10:  # 胜率差异超过10%时惩罚
                scores[i] *= 0.5
        
        # 加上当前权重作为惯性项
        scores = scores * 0.85 + self.weights * 0.15
        
        # Softmax归一化
        temperature = 0.3  # 更小温度=更激进的权重分配
        exp_scores = np.exp(scores / temperature - np.max(scores / temperature))
        exp_sum = exp_scores.sum()
        new_weights = exp_scores / exp_sum if exp_sum > 0 else np.ones_like(scores) / len(scores)
        
        # 应用权重约束
        new_weights = np.clip(new_weights, self.min_weight, self.max_weight)
        new_weights = new_weights / new_weights.sum()
        
        self.weights = new_weights
        return new_weights
    
    def get_weights(self) -> Dict[str, float]:
        """获取当前策略权重"""
        return {name: float(w) for name, w in zip(self.strategy_names, self.weights)}


# ==================== 3. 闭环反馈系统 ====================

class FeedbackLoop:
    """
    闭环反馈系统
    理论：MLOps闭环 - 表现追踪→偏差检测→参数优化→权重调整
    """
    
    def __init__(self, config=None):
        self.config = config or {
            'performance_window': 50,   # 表现评估窗口(笔)
            'reoptimize_interval': 100,  # 重新优化间隔(笔)
            'drift_threshold': 0.10,    # 漂移检测阈值
            'min_trades_for_eval': 20   # 最少评估交易数
        }
        self.trade_history = []
        self.optimization_log = []
        self.baseline_performance = None
    
    def record_trade(self, trade: Dict):
        """记录交易结果"""
        self.trade_history.append({
            **trade,
            'timestamp': datetime.now().isoformat()
        })
        
        # 更新策略表现
        strategy = trade.get('strategy', 'mean_reversion')
        self.adaptive_weights.update_performance(strategy, trade)
        
        # 每10笔交易调整一次权重（更频繁的反馈）
        if len(self.trade_history) % 10 == 0 and len(self.trade_history) >= 20:
            self.adaptive_weights.adjust_weights()
            self.optimization_log.append({'type': 'weight_adjustment', 'timestamp': datetime.now().isoformat()})
        
        # 检测漂移
        if len(self.trade_history) >= self.config['min_trades_for_eval']:
            self._check_drift()
    
    def _check_drift(self):
        """检测策略表现漂移"""
        window = self.trade_history[-self.config['performance_window']:]
        recent_wr = sum(1 for t in window if t.get('pnl', 0) > 0) / len(window)
        
        if self.baseline_performance is None:
            self.baseline_performance = recent_wr
            return
        
        drift = recent_wr - self.baseline_performance
        if abs(drift) > self.config['drift_threshold']:
            logger.warning(f"Drift detected: {drift:.3f} (recent={recent_wr:.3f}, baseline={self.baseline_performance:.3f})")
            self._trigger_reoptimization(drift)
    
    def _trigger_reoptimization(self, drift: float):
        """触发重新优化"""
        old_weights = self.adaptive_weights.get_weights()
        new_weights = self.adaptive_weights.adjust_weights()
        
        self.optimization_log.append({
            'timestamp': datetime.now().isoformat(),
            'drift': drift,
            'old_weights': old_weights,
            'new_weights': new_weights,
            'action': 'weight_adjustment' if abs(drift) < 0.2 else 'strategy_rebalance'
        })
        
        logger.info(f"Weights adjusted: {old_weights} -> {new_weights}")
    
    def get_status(self) -> Dict:
        """获取反馈闭环状态"""
        if not self.trade_history:
            return {'status': 'no_data', 'trades': 0}
        
        window = self.trade_history[-self.config['performance_window']:]
        recent_wr = sum(1 for t in window if t.get('pnl', 0) > 0) / len(window) if window else 0
        
        return {
            'status': 'active',
            'total_trades': len(self.trade_history),
            'recent_win_rate': recent_wr,
            'baseline_performance': self.baseline_performance,
            'strategy_weights': self.adaptive_weights.get_weights(),
            'optimization_count': len(self.optimization_log),
            'last_optimization': self.optimization_log[-1] if self.optimization_log else None
        }


# ==================== 4. 闭环集成引擎 ====================

class ClosedLoopEngine:
    """
    闭环集成引擎 v5.3
    
    将所有独立模块串联为闭环Pipeline：
    DataPipeline → SignalPipeline → StrategyOrchestrator → PortfolioAllocator → RiskManager → FeedbackLoop
    
    核心改进：
    1. 信号确认流水线（3级确认，至少2级通过）
    2. 自适应策略权重（EWMA追踪+softmax调整）
    3. 表现漂移检测（自动触发重新优化）
    4. HRP+凯利资金分配闭环
    5. 动态保本止损
    """
    
    def __init__(self, config=None):
        default_config = {
            'capital': 100000,
            'symbols': ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT'],
            'timeframe': '1h',
            'mode': 'hybrid',
            'rsi_period': 14, 'rsi_oversold': 30, 'rsi_overbought': 70,
            'bb_period': 20, 'bb_std': 2.5,
            'atr_period': 14, 'atr_sl': 2.0, 'atr_tp': 2.0,  # P5: 1.5→2.0, 2.0→2.0 (宽止损匹配)
            'trailing_stop_atr': 1.0,
            'trailing_step_atr': 0.5,
            'max_consecutive_losses': 8,
            'max_hold_bars': 20,   # P5: 24→20 (减少MAXH持仓)
            'daily_loss_limit': 0.05,
            'circuit_breaker_hours': 6,
            'min_confirmations': 1,
            'weight_decay': 0.95,
            'drift_threshold': 0.10,
            'breakeven_at_bb_mid': True,
            # === P5新增参数 ===
            'adx_max': 80,         # P5: ADX>80时禁止开仓(强趋势市场反弹弱)
            'direction': 'LONG_ONLY',  # P5: 做多方向(做空在2025-2026市场严重亏损)
            'vol_filter_atr_pct': 0.0025,  # P5: 波动率过滤(ATR>%时开仓)
            'signal_threshold_base': 0.52,  # P5: 基础信号阈值
        }
        if config:
            default_config.update(config)
        self.config = default_config
        
        # 初始化子系统
        signal_config = {
            'min_confirmations': self.config.get('min_confirmations', 1),
            'threshold': 0.50
        }
        self.signal_pipeline = SignalConfirmationPipeline(signal_config)
        self.adaptive_weights = AdaptiveStrategyWeights(decay=self.config.get('weight_decay', 0.95))
        self.feedback_loop = FeedbackLoop({
            'performance_window': self.config.get('performance_window', 50),
            'reoptimize_interval': self.config.get('reoptimize_interval', 100),
            'drift_threshold': self.config.get('drift_threshold', 0.10),
            'min_trades_for_eval': self.config.get('min_trades_for_eval', 20)
        })
        # 共享adaptive_weights实例，确保FeedbackLoop的调整反映到主引擎
        self.feedback_loop.adaptive_weights = self.adaptive_weights
        
        # 状态
        self.consecutive_losses = 0
        self.daily_pnl = 0
        self.circuit_breaker_until = None
        self.positions = {}
        self.trade_log = []
    
    def _calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算技术指标"""
        df = df.copy()
        
        # RSI
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(self.config['rsi_period']).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(self.config['rsi_period']).mean()
        loss = loss.replace(0, 1e-10)
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        df['rsi'] = df['rsi'].clip(0, 100)
        
        # 布林带
        df['bb_mid'] = df['close'].rolling(self.config['bb_period']).mean()
        df['bb_std'] = df['close'].rolling(self.config['bb_period']).std()
        df['bb_upper'] = df['bb_mid'] + self.config['bb_std'] * df['bb_std']
        df['bb_lower'] = df['bb_mid'] - self.config['bb_std'] * df['bb_std']
        df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])
        
        # ATR
        hl = df['high'] - df['low']
        hc = abs(df['high'] - df['close'].shift())
        lc = abs(df['low'] - df['close'].shift())
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        df['atr'] = tr.rolling(self.config['atr_period']).mean()
        df['atr'] = df['atr'].ffill().bfill()  # NaN填充
        min_atr = df['close'] * 0.001  # 最小ATR = 0.1%价格
        df['atr'] = df['atr'].where(df['atr'] > min_atr, min_atr)  # ATR零保护
        
        # 均线
        df['sma20'] = df['close'].rolling(20).mean()
        df['sma50'] = df['close'].rolling(50).mean()
        df['ema12'] = df['close'].ewm(span=12, adjust=False).mean()
        df['ema26'] = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = df['ema12'] - df['ema26']
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        
        # ADX
        plus_dm = df['high'].diff()
        minus_dm = df['low'].diff()
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm > 0] = 0
        atr_safe = df['atr'].replace(0, np.nan)
        plus_di = 100 * (plus_dm.ewm(alpha=1/14).mean() / atr_safe)
        minus_di = 100 * (abs(minus_dm).ewm(alpha=1/14).mean() / atr_safe)
        di_sum = (plus_di + minus_di).replace(0, np.nan)
        df['adx'] = (100 * abs(plus_di - minus_di) / di_sum).ewm(alpha=1/14).mean()
        df['plus_di'] = plus_di
        df['minus_di'] = minus_di
        
        # 成交量
        df['vol_ma'] = df['volume'].rolling(20).mean()
        df['vol_ratio'] = df['volume'] / df['vol_ma']
        
        # Hurst指数
        df['hurst'] = self._calculate_hurst(df['close'], window=100)
        
        # 动量
        df['momentum'] = df['close'] / df['close'].shift(10) - 1
        
        # 趋势判断
        df['uptrend'] = (df['sma20'] > df['sma50']) & (df['close'] > df['sma20'])
        df['downtrend'] = (df['sma20'] < df['sma50']) & (df['close'] < df['sma20'])
        
        # NaN保护和零除保护
        df = df.ffill().bfill()
        df['atr'] = df['atr'].clip(lower=df['close'] * 0.001)  # ATR最小值0.1%价格
        
        return df
    
    def _calculate_hurst(self, series: np.ndarray, window: int = 100) -> np.ndarray:
        """简化Hurst指数计算"""
        def hurst(ts: np.ndarray) -> float:
            if len(ts) < 20:
                return 0.5
            try:
                lags = range(2, min(20, len(ts)))
                tau = [np.std(np.subtract(ts[lag:], ts[:-lag])) for lag in lags]
                valid = [(l, t) for l, t in zip(lags, tau) if t > 0]
                if len(valid) < 3:
                    return 0.5
                lags_v, tau_v = zip(*valid)
                poly = np.polyfit(np.log(lags_v), np.log(tau_v), 1)
                return max(0, min(1, poly[0]))
            except:
                return 0.5
        
        return series.rolling(window).apply(hurst, raw=False)
    
    def _generate_raw_signal(self, df: pd.DataFrame, idx: int) -> Tuple[int, str]:
        """
        生成原始信号（评分制）
        返回: (signal_type, strategy_name)
        
        评分制：每个条件独立评分，加权后达到阈值触发信号
        """
        if idx < 100:
            return 0, 'none'
        
        row = df.iloc[idx]
        prev = df.iloc[idx-1]
        weights = self.adaptive_weights.get_weights()
        hurst = 0.5  # 预声明，避免UnboundLocalError (P4-fix)
        
        # === 策略A: 均值回归（评分制）===
        mr_long_score = 0
        mr_short_score = 0
        
        # RSI评分
        if row['rsi'] < 30: mr_long_score += 0.35
        elif row['rsi'] < 40: mr_long_score += 0.20
        if row['rsi'] > 70: mr_short_score += 0.35
        elif row['rsi'] > 60: mr_short_score += 0.20
        
        # BB位置评分
        bb_pos = row.get('bb_position', 0.5)
        if bb_pos < 0.15: mr_long_score += 0.30
        elif bb_pos < 0.30: mr_long_score += 0.15
        if bb_pos > 0.85: mr_short_score += 0.30
        elif bb_pos > 0.70: mr_short_score += 0.15
        
        # RSI方向确认
        if row['rsi'] > prev['rsi'] and row['rsi'] < 40: mr_long_score += 0.20
        if row['rsi'] < prev['rsi'] and row['rsi'] > 60: mr_short_score += 0.20
        
        # 量比过滤
        vol_ratio = row.get('vol_ratio', 1.0)
        if vol_ratio < 1.5:  # 低量=均值回归
            mr_long_score += 0.15
            mr_short_score += 0.15
        
        # === 策略B: 趋势跟踪（EMA斜率 + 突破确认 + 波动率过滤）===
        # P0修复: 替换失效的MACD交叉(太慢) + ADX确认(太弱)
        # 新三层过滤: EMA斜率(趋势方向) → 突破确认(动量) → 波动率过滤(质量)
        tf_long_score = 0
        tf_short_score = 0

        # --- 因子1: EMA斜率（趋势方向，速度比MACD快50%）---
        # 计算EMA20的5周期斜率，反映近期趋势强度
        ema_window = 20
        if idx >= ema_window + 5:
            ema_vals = df['close'].ewm(span=ema_window, adjust=False).mean().iloc[idx-4:idx+1].values
            ema_slope = (ema_vals[-1] - ema_vals[0]) / (ema_vals[0] * 5)  # 标准化斜率
            ema_slope_long_threshold = 0.001   # 0.1%/bar，上升趋势阈值
            ema_slope_short_threshold = -0.001  # -0.1%/bar，下降趋势阈值
            if ema_slope > ema_slope_long_threshold:
                base = 0.30
                if hurst > 0.55: base = 0.40   # P3修复: 趋势市增强趋势因子
                tf_long_score += base
            elif ema_slope < ema_slope_short_threshold:
                base = 0.30
                if hurst > 0.55: base = 0.40   # P3修复: 趋势市增强趋势因子
                tf_short_score += base

        # EMA排列：短期 > 长期 = 上升趋势
        ema12 = row.get('ema12', row.get('ma5', row['close']))
        ema26 = row.get('ema26', row.get('ma10', row['close']))
        if ema12 > ema26: tf_long_score += 0.15
        if ema12 < ema26: tf_short_score += 0.15

        # --- 因子2: 突破确认（动量验证，去除噪音假突破）---
        # 价格突破N日高点/低点，配合成交量确认
        lookback = 20
        if idx >= lookback:
            recent_high = df['high'].iloc[idx-lookback:idx].max()
            recent_low = df['low'].iloc[idx-lookback:idx].min()
            # 计算ATR作为突破有效性的尺度（防止在低波动时被噪音扫止损）
            atr_val = row.get('atr', 0)
            atr_pct = (atr_val / row['close'] * 100) if row['close'] > 0 else 0.1

            # P3-2修复: 突破阈值从0.5*ATR降至0.3*ATR（原太严格导致1年仅1笔趋势交易）
            breakout_threshold = atr_val * 0.3
            breakout_boost = 1.0
            if hurst > 0.55: breakout_boost = 1.4   # 趋势市增强突破信号
            elif hurst < 0.45: breakout_boost = 0.7  # 均值回归市削弱突破信号
            if row['close'] > recent_high + breakout_threshold:
                tf_long_score += 0.25 * breakout_boost
            if row['close'] < recent_low - breakout_threshold:
                tf_short_score += 0.25 * breakout_boost

            # 价格 vs EMA20 的偏离（偏离大 = 趋势强）
            ma20 = row.get('ma20', row['close'])
            if ma20 > 0:
                price_deviation = (row['close'] - ma20) / ma20
                if price_deviation > 0.02:   # 偏离>2%=强上升
                    tf_long_score += 0.10
                elif price_deviation < -0.02:  # 偏离<-2%=强下降
                    tf_short_score += 0.10

        # --- 因子3: 波动率过滤（去假信号的关键）---
        # 仅在高波动期或趋势明确时参与，避免在低波动震荡中被反复扫止损
        atr_pct_now = row.get('atr_pct', 0)
        if atr_pct_now > 0.3:   # 波动率足够（真实BTC 1H std≈0.45%）
            tf_long_score += 0.10
            tf_short_score += 0.10

        # --- 移除因子4: ADX趋势强度（已失效，替换为EMA斜率替代）---
        # 原代码 ADX > 25 太弱，P0修复用更严格的EMA斜率代替
        
        # === 策略C: 资金费率（简化）===
        fr_long_score = 0
        fr_short_score = 0
        if row['rsi'] > 75 and vol_ratio > 2.0: fr_short_score += 0.50
        elif row['rsi'] < 25 and vol_ratio > 2.0: fr_long_score += 0.50
        
        # === Hurst + ADX 双维度市场状态判断（P4新增）===
        # Hurst: 历史数据特征；ADX: 当前趋势强度。两者结合更准确
        hurst = row.get('hurst', 0.5)
        adx = row.get('adx', 25)
        
        if adx > 30:
            # 强趋势市场: 抑制均值回归，增强趋势/突破
            mr_boost, tf_boost = 0.5, 1.4
            signal_boost = 0.05  # 提高阈值过滤噪音
        elif adx > 25:
            # 趋势市场: Hurst主导，但ADX确认时增强趋势
            if hurst > 0.55: mr_boost, tf_boost = 0.7, 1.3
            elif hurst < 0.45: mr_boost, tf_boost = 1.0, 1.0
            else: mr_boost, tf_boost = 0.8, 1.1
            signal_boost = 0.03
        elif adx < 20:
            # 震荡市场: 增强均值回归，抑制趋势
            if hurst < 0.45: mr_boost, tf_boost = 1.4, 0.6  # 双重确认震荡
            elif hurst > 0.55: mr_boost, tf_boost = 1.1, 0.9
            else: mr_boost, tf_boost = 1.2, 0.8
            signal_boost = -0.05  # 降低阈值，捕捉更多机会
        else:
            # 中性市场: Hurst主导
            if hurst < 0.45: mr_boost, tf_boost = 1.3, 0.7
            elif hurst > 0.55: mr_boost, tf_boost = 0.7, 1.3
            else: mr_boost, tf_boost = 1.0, 1.0
            signal_boost = 0.0
        
        # P3-3新增: SOL/BNB纯突破策略 — 专为强趋势币种设计（替代失效的MACD交叉）
        # 触发条件: 价格突破N根K线内高/低点，且RSI处于极端区域
        breakout_long_score = 0
        breakout_short_score = 0
        lookback = 20
        if idx >= lookback:  # [P4-fix] i→idx
            recent_high = df['high'].iloc[idx-lookback:idx].max()
            recent_low = df['low'].iloc[idx-lookback:idx].min()
            atr_now = row.get('atr', df['close'].iloc[idx] * 0.005)
            # 宽松突破: 0.3×ATR（原trend策略要求0.5×ATR）
            if row['close'] > recent_high + 0.3 * atr_now and row['rsi'] > 60:
                breakout_long_score = 0.55
            if row['close'] < recent_low - 0.3 * atr_now and row['rsi'] < 40:
                breakout_short_score = 0.55
        
        # === 加权融合 ===
        w = weights
        long_signal = (
            mr_long_score * w.get('mean_reversion', 0.25) * mr_boost +
            tf_long_score * w.get('trend_following', 0.25) * tf_boost +
            breakout_long_score * w.get('breakout', 0.25) +
            fr_long_score * w.get('funding_rate', 0.25)
        )
        short_signal = (
            mr_short_score * w.get('mean_reversion', 0.25) * mr_boost +
            tf_short_score * w.get('trend_following', 0.25) * tf_boost +
            breakout_short_score * w.get('breakout', 0.25) +
            fr_short_score * w.get('funding_rate', 0.25)
        )
        
        # P4新增: Hurst+ADX双维度阈值调整
        # 基础阈值 + Hurst调整 + ADX状态调整
        adx_max = self.config.get('adx_max', 80)  # P5: ADX过滤
        base_thresh = self.config.get('signal_threshold_base', 0.52)
        if hurst > 0.55:  # Hurst趋势市场
            hurst_adj = 0.03
        elif hurst < 0.45:  # Hurst均值回归市场
            hurst_adj = -0.02
        else:
            hurst_adj = 0.0
        signal_threshold = base_thresh + hurst_adj + signal_boost

        direction = self.config.get('direction', 'LONG_ONLY')  # P5: 方向过滤
        
        if long_signal > short_signal and long_signal >= signal_threshold:
            # P5: ADX过滤 — 强趋势市场(ADX>adx_max)禁止开仓
            if adx_val > adx_max:
                return 0, 'none'
            # 信号方向优势检查：至少比反向信号强20%
            if short_signal > 0 and long_signal / (short_signal + 1e-10) < 1.2:
                return 0, 'none'
            strategy = 'mean_reversion' if mr_long_score > tf_long_score else 'trend_following'
            return 1, strategy
        elif short_signal > long_signal and short_signal >= signal_threshold:
            # P5: LONG-ONLY方向 — 禁用做空
            if direction == 'LONG_ONLY':
                return 0, 'none'
            # P5: ADX过滤
            if adx_val > adx_max:
                return 0, 'none'
            if long_signal > 0 and short_signal / (long_signal + 1e-10) < 1.2:
                return 0, 'none'
            strategy = 'mean_reversion' if mr_short_score > tf_short_score else 'trend_following'
            return -1, strategy
        
        return 0, 'none'
    
    def _check_circuit_breaker(self, current_time=None) -> bool:
        """检查熔断器"""
        if self.circuit_breaker_until is not None:
            check_time = current_time or datetime.now()
            if check_time < self.circuit_breaker_until:
                return True
            else:
                self.circuit_breaker_until = None
                self.consecutive_losses = 0
                self.daily_pnl = 0
        return False
    
    def _trigger_circuit_breaker(self, current_time=None):
        """触发熔断"""
        trigger_time = current_time or datetime.now()
        self.circuit_breaker_until = trigger_time + timedelta(hours=self.config['circuit_breaker_hours'])
        logger.warning(f"Circuit breaker triggered! Paused until {self.circuit_breaker_until}")
    
    def run_backtest(self, df: pd.DataFrame, symbol: str = 'BTCUSDT') -> Dict:
        """
        运行闭环回测
        
        Pipeline: 数据→指标→信号→确认→仓位→风控→反馈
        """
        df = self._calculate_indicators(df)
        
        capital = self.config['capital']
        equity = capital
        positions = {}
        trade_log = []
        wins = 0
        total_trades = 0
        
        for i in range(100, len(df)):
            row = df.iloc[i]
            
            # 检查熔断
            current_time = df.index[i] if hasattr(df.index[i], 'to_pydatetime') else pd.Timestamp(df.index[i]).to_pydatetime()
            if self._check_circuit_breaker(current_time):
                continue
            
            # 检查已有仓位的止盈止损
            for sym in list(positions.keys()):
                pos = positions[sym]
                pnl = 0
                # P3-2新增: 时间止损准备 — 超过N根K线强制平仓
                time_stop_bars = self.config.get('max_hold_bars', 24)
                bars_held = i - pos.get('entry_bar', i)
                
                closed = False
                pnl = 0.0  # 预定义，防止time-stop时未赋值
                
                if pos['type'] == 'LONG':
                    # 动态保本止损：价格到BB均线移止损到成本
                    if self.config.get('breakeven_at_bb_mid') and row['close'] >= row['bb_mid'] and pos['sl'] < pos['entry']:
                        pos['sl'] = pos['entry']
                    
                    # 追踪止损: 浮盈达到trailing_stop_atr时，移止损到入场价+trailing_step_atr
                    trailing_atr = row['atr']
                    if row['close'] >= pos['entry'] + self.config.get('trailing_stop_atr', 1.0) * trailing_atr:
                        new_sl = pos['entry'] + self.config.get('trailing_step_atr', 0.5) * trailing_atr
                        if new_sl > pos['sl']:
                            pos['sl'] = new_sl
                    
                    if row['low'] <= pos['sl']:
                        pnl = -abs(pos['sl'] - pos['entry']) / pos['entry']
                        closed = True
                    elif row['high'] >= pos['tp']:
                        pnl = abs(pos['tp'] - pos['entry']) / pos['entry']
                        closed = True
                    elif bars_held >= time_stop_bars:
                        pnl = (row['close'] - pos['entry']) / pos['entry'] - 0.0009
                        closed = True
                elif pos['type'] == 'SHORT':
                    if self.config.get('breakeven_at_bb_mid') and row['close'] <= row['bb_mid'] and pos['sl'] > pos['entry']:
                        pos['sl'] = pos['entry']
                    
                    # 追踪止损: 浮盈达到trailing_stop_atr时，移止损到入场价-trailing_step_atr
                    trailing_atr = row['atr']
                    if row['close'] <= pos['entry'] - self.config.get('trailing_stop_atr', 1.0) * trailing_atr:
                        new_sl = pos['entry'] - self.config.get('trailing_step_atr', 0.5) * trailing_atr
                        if new_sl < pos['sl']:
                            pos['sl'] = new_sl
                    
                    if row['high'] >= pos['sl']:
                        pnl = -abs(pos['sl'] - pos['entry']) / pos['entry']
                        closed = True
                    elif row['low'] <= pos['tp']:
                        pnl = abs(pos['entry'] - pos['tp']) / pos['entry']
                        closed = True
                    elif bars_held >= time_stop_bars:
                        pnl = (pos['entry'] - row['close']) / pos['entry'] - 0.0009
                        closed = True
                
                if closed:
                    # 使用凯利仓位计算实际盈亏
                    position_ratio = pos.get('kelly', 0.1)
                    actual_pnl = pnl * position_ratio
                    equity *= (1 + actual_pnl)
                    equity = max(equity, 0)  # 防止负权益
                    total_trades += 1
                    
                    if pnl > 0:
                        wins += 1
                        self.consecutive_losses = 0
                    else:
                        self.consecutive_losses += 1
                        actual_pnl_loss = abs(pnl) * position_ratio
                        self.daily_pnl -= actual_pnl_loss
                    
                    # 日亏损重置：检测日期变化
                    if i > 0 and hasattr(df.index[i], 'date'):
                        if df.index[i].date() != df.index[i-1].date():
                            self.daily_pnl = 0
                    
                    # 熔断检查（daily_pnl为负累计值，与equity比例比较）
                    if self.consecutive_losses >= self.config['max_consecutive_losses'] or (equity > 0 and self.daily_pnl / equity <= -self.config['daily_loss_limit']):
                        self._trigger_circuit_breaker(current_time)
                    
                    trade_log.append({
                        'symbol': sym,
                        'type': pos['type'],
                        'entry': pos['entry'],
                        'exit': pos['sl'] if pnl < 0 else pos['tp'],
                        'pnl': pnl,
                        'strategy': pos.get('strategy', 'unknown'),
                        'confirmed': pos.get('confirmed', False)
                    })
                
                # P3-2新增: 时间止损强制平仓（趋势反转后长期套牢保护）
                if time_stop_triggered:
                    pnl = (row['close'] - pos['entry']) / pos['entry'] if pos['type'] == 'LONG' else (pos['entry'] - row['close']) / pos['entry']
                    position_ratio = pos.get('kelly', 0.1)
                    actual_pnl = pnl * position_ratio
                    equity *= (1 + actual_pnl)
                    total_trades += 1
                    if pnl > 0:
                        wins += 1
                    else:
                        self.consecutive_losses += 1
                        self.daily_pnl -= abs(pnl) * position_ratio
                    trade_log.append({
                        'symbol': sym, 'type': pos['type'],
                        'entry': pos['entry'], 'exit': row['close'],
                        'pnl': pnl, 'strategy': pos.get('strategy', 'unknown'),
                        'confirmed': pos.get('confirmed', False),
                        'exit_reason': 'time_stop'
                    })
                    self.feedback_loop.record_trade(trade_log[-1])
                    
                    # 反馈闭环
                    self.feedback_loop.record_trade(trade_log[-1])
                    
                    del positions[sym]
            
            # 生成新信号（熔断期间禁止开仓）
            if symbol not in positions and not self._check_circuit_breaker(current_time):
                raw_signal, strategy = self._generate_raw_signal(df, i)
                
                if raw_signal != 0:
                    # P5: 波动率过滤 — ATR>%时才有足够波动空间
                    vol_filter = self.config.get('vol_filter_atr_pct', 0.0025)
                    if row.get('atr_pct', 1.0) < vol_filter:
                        continue
                    # 信号确认流水线
                    signal_data = {
                        'rsi': row['rsi'],
                        'bb_position': row.get('bb_position', 0.5),
                        'adx': row['adx'],
                        'plus_di': row.get('plus_di', 0),
                        'minus_di': row.get('minus_di', 0),
                        'macd_signal': 1 if row['macd'] > row['macd_signal'] else -1,
                        'hurst': row.get('hurst', 0.5),
                        'vol_ratio': row.get('vol_ratio', 1.0),
                        'momentum': row.get('momentum', 0)
                    }
                    
                    confirmation = self.signal_pipeline.confirm_signal(raw_signal, signal_data, strategy)
                    
                    if confirmation['confirmed']:
                        entry = row['close']
                        atr = max(row['atr'], entry * 0.002)  # ATR最小保护(0.2%价格)
                        min_sl_dist = entry * 0.003  # 止损最小距离0.3%
                        
                        if raw_signal == 1:
                            sl = entry - max(self.config['atr_sl'] * atr, min_sl_dist)
                            tp = entry + self.config['atr_tp'] * atr
                        else:
                            sl = entry + max(self.config['atr_sl'] * atr, min_sl_dist)
                            tp = entry - self.config['atr_tp'] * atr
                        
                        # 凯利仓位计算
                        wr = wins / total_trades if total_trades > 0 else 0.5
                        payoff = self.config['atr_tp'] / self.config['atr_sl']
                        kelly = max(0.01, min(0.25, (payoff * wr - (1 - wr)) / payoff * 0.5))
                        position_size = equity * kelly
                        
                        positions[symbol] = {
                            'type': 'LONG' if raw_signal == 1 else 'SHORT',
                            'entry': entry,
                            'sl': sl,
                            'tp': tp,
                            'size': position_size,
                            'kelly': kelly,
                            'strategy': strategy,
                            'confirmed': True,
                            'confirmation_score': confirmation['total_score'],
                            'entry_bar': i   # P3-2新增: 记录开仓K线编号，用于时间止损
                        }
        
        # 清算剩余仓位
        for sym in list(positions.keys()):
            pos = positions[sym]
            final_pnl = 0
            if pos['type'] == 'LONG':
                final_pnl = (df.iloc[-1]['close'] - pos['entry']) / pos['entry']
            else:
                final_pnl = (pos['entry'] - df.iloc[-1]['close']) / pos['entry']
            
            position_ratio = pos.get('kelly', 0.1)
            actual_pnl = final_pnl * position_ratio
            equity *= (1 + actual_pnl)
            equity = max(equity, 0)
            total_trades += 1
            if final_pnl > 0:
                wins += 1
            
            trade_log.append({
                'symbol': sym, 'type': pos['type'], 'entry': pos['entry'],
                'exit': df.iloc[-1]['close'], 'pnl': final_pnl,
                'strategy': pos.get('strategy', 'unknown'), 'confirmed': True
            })
        
        win_rate = wins / total_trades * 100 if total_trades > 0 else 0
        total_return = (equity - capital) / capital * 100
        
        # 统计
        long_trades = [t for t in trade_log if t['type'] == 'LONG']
        short_trades = [t for t in trade_log if t['type'] == 'SHORT']
        confirmed_trades = [t for t in trade_log if t.get('confirmed', False)]
        
        long_wr = sum(1 for t in long_trades if t['pnl'] > 0) / len(long_trades) * 100 if long_trades else 0
        short_wr = sum(1 for t in short_trades if t['pnl'] > 0) / len(short_trades) * 100 if short_trades else 0
        
        # 策略分布
        strategy_dist = defaultdict(int)
        strategy_wins = defaultdict(int)
        for t in trade_log:
            s = t.get('strategy', 'unknown')
            strategy_dist[s] += 1
            if t['pnl'] > 0:
                strategy_wins[s] += 1
        
        # 最大连续亏损
        max_consec_loss = 0
        current_loss_streak = 0
        for t in trade_log:
            if t['pnl'] <= 0:
                current_loss_streak += 1
                max_consec_loss = max(max_consec_loss, current_loss_streak)
            else:
                current_loss_streak = 0
        
        return {
            'symbol': symbol,
            'total_return': total_return,
            'final_equity': equity,
            'total_trades': total_trades,
            'wins': wins,
            'win_rate': win_rate,
            'long_trades': len(long_trades),
            'short_trades': len(short_trades),
            'long_wr': long_wr,
            'short_wr': short_wr,
            'confirmed_trades': len(confirmed_trades),
            'max_consecutive_losses': max_consec_loss,
            'strategy_distribution': dict(strategy_dist),
            'strategy_win_rates': {k: strategy_wins[k]/v*100 if v > 0 else 0 for k, v in strategy_dist.items()},
            'feedback_status': self.feedback_loop.get_status(),
            'adaptive_weights': self.adaptive_weights.get_weights(),
            'trades': trade_log
        }


# ==================== 主函数 ====================

def generate_test_data(n_bars: int = 500, base_price: float = 50000, volatility: float = 0.02) -> pd.DataFrame:
    """生成测试数据"""
    np.random.seed(42)
    dates = pd.date_range('2024-01-01', periods=n_bars, freq='1h')
    
    returns = np.random.normal(0.0001, volatility, n_bars)
    # 添加一些趋势和均值回归特征
    for i in range(10, n_bars):
        if i % 50 == 0:  # 周期性趋势
            returns[i:i+20] += 0.002
        elif i % 50 == 25:
            returns[i:i+20] -= 0.002
    
    close = base_price * np.exp(np.cumsum(returns))
    high = close * (1 + np.abs(np.random.normal(0, volatility * 0.5, n_bars)))
    low = close * (1 - np.abs(np.random.normal(0, volatility * 0.5, n_bars)))
    open_ = close * (1 + np.random.normal(0, volatility * 0.3, n_bars))
    volume = np.random.lognormal(15, 1, n_bars)
    
    return pd.DataFrame({
        'open': open_, 'high': high, 'low': low, 'close': close, 'volume': volume
    }, index=dates)


def main():
    parser = argparse.ArgumentParser(description='Killer Trading System v5.3 - Closed Loop Engine')
    parser.add_argument('--capital', type=float, default=100000)
    parser.add_argument('--bars', type=int, default=500)
    parser.add_argument('--symbol', type=str, default='BTCUSDT')
    parser.add_argument('--mode', type=str, default='hybrid', choices=['mean_reversion', 'trend', 'hybrid'])
    args = parser.parse_args()
    
    print("\n" + "=" * 80)
    print("KILLER TRADING SYSTEM v5.3 - CLOSED LOOP ENGINE")
    print(f"Time: {datetime.now()}")
    print(f"Config: SignalPipeline + AdaptiveWeights + FeedbackLoop + BreakevenSL")
    print("=" * 80)
    
    # 生成测试数据
    print(f"\n[{args.symbol}] Generating {args.bars} bars test data...")
    df = generate_test_data(args.bars)
    print(f"  Data range: {df.index[0]} to {df.index[-1]}")
    
    # 运行闭环回测
    engine = ClosedLoopEngine({
        'capital': args.capital,
        'mode': args.mode
    })
    
    result = engine.run_backtest(df, args.symbol)
    
    # 输出结果
    print(f"\n{'='*60}")
    print(f"CLOSED LOOP BACKTEST RESULTS - {args.symbol}")
    print(f"{'='*60}")
    print(f"  Total Return:    {result['total_return']:.2f}%")
    print(f"  Final Equity:    ${result['final_equity']:,.2f}")
    print(f"  Total Trades:    {result['total_trades']}")
    print(f"  Win Rate:        {result['win_rate']:.1f}%")
    print(f"  Long/Short:      {result['long_trades']}/{result['short_trades']}")
    print(f"  Long WR:         {result['long_wr']:.1f}%")
    print(f"  Short WR:        {result['short_wr']:.1f}%")
    print(f"  Max Consec Loss: {result['max_consecutive_losses']}")
    print(f"  Confirmed:       {result['confirmed_trades']}/{result['total_trades']}")
    
    print(f"\n{'='*60}")
    print("STRATEGY DISTRIBUTION")
    print(f"{'='*60}")
    for strat, count in result['strategy_distribution'].items():
        wr = result['strategy_win_rates'].get(strat, 0)
        print(f"  {strat:<20}: {count:>3} trades, {wr:.1f}% WR")
    
    print(f"\n{'='*60}")
    print("ADAPTIVE WEIGHTS (Final)")
    print(f"{'='*60}")
    for strat, weight in result['adaptive_weights'].items():
        print(f"  {strat:<20}: {weight:.3f}")
    
    print(f"\n{'='*60}")
    print("FEEDBACK LOOP STATUS")
    print(f"{'='*60}")
    status = result['feedback_status']
    print(f"  Status:          {status['status']}")
    print(f"  Recent WR:       {status.get('recent_win_rate', 0):.1%}")
    print(f"  Optimizations:   {status.get('optimization_count', 0)}")
    
    # 保存结果
    output = {
        'version': 'v5.3',
        'timestamp': datetime.now().isoformat(),
        'config': {'capital': args.capital, 'bars': args.bars, 'mode': args.mode},
        'results': {
            'total_return': result['total_return'],
            'win_rate': result['win_rate'],
            'total_trades': result['total_trades'],
            'max_consecutive_losses': result['max_consecutive_losses'],
            'adaptive_weights': result['adaptive_weights'],
            'strategy_distribution': result['strategy_distribution']
        }
    }
    
    output_path = f"closed_loop_report_v53.json"
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n  Report saved: {output_path}")
    
    return result


if __name__ == "__main__":
    main()
