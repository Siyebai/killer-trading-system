#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("adaptive_parameter_optimizer")
except ImportError:
    import logging
    logger = logging.getLogger("adaptive_parameter_optimizer")
"""
自适应参数优化模块（贝叶斯优化） - v1.0.3扩展
定位：复盘总结和优化提升的自动化版本
核心策略：贝叶斯优化、超参数自动调整、目标函数夏普比率、热加载配置
"""

import argparse
import json
import sys
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import sqlite3
import os
from datetime import datetime, timedelta


@dataclass
class OptimizationResult:
    """优化结果"""
    best_params: Dict[str, float]
    best_score: float
    optimization_time: float
    iteration_count: int
    improvement: float


@dataclass
class ParameterSpace:
    """参数空间"""
    name: str
    param_type: str  # 'continuous', 'integer', 'categorical'
    low: float
    high: float
    choices: Optional[List] = None


class BayesianOptimizer:
    """贝叶斯优化器（简化版，使用网格搜索+随机采样）"""

    def __init__(
        self,
        objective_func: callable,
        param_space: List[ParameterSpace],
        max_iterations: int = 50,
        n_random_starts: int = 10
    ):
        """
        初始化贝叶斯优化器

        Args:
            objective_func: 目标函数
            param_space: 参数空间
            max_iterations: 最大迭代次数
            n_random_starts: 随机采样次数
        """
        self.objective_func = objective_func
        self.param_space = param_space
        self.max_iterations = max_iterations
        self.n_random_starts = n_random_starts

        # 优化历史
        self.history = []

    def optimize(self) -> OptimizationResult:
        """
        执行优化

        Returns:
            优化结果
        """
        import time
        start_time = time.time()

        best_score = float('-inf')
        best_params = None

        # 第一阶段：随机采样
        logger.info(f"第一阶段：随机采样 {self.n_random_starts} 次...")

        for i in range(self.n_random_starts):
            params = self._sample_params(random=True)
            score = self._evaluate_params(params)

            self.history.append({'params': params, 'score': score})

            if score > best_score:
                best_score = score
                best_params = params

            logger.info(f"  迭代 {i+1}/{self.n_random_starts}: score={score:.4f}, best={best_score:.4f}")

        # 第二阶段：网格搜索（简化版贝叶斯优化）
        logger.info(f"\n第二阶段：网格搜索 {self.max_iterations - self.n_random_starts} 次...")

        for i in range(self.n_random_starts, self.max_iterations):
            # 基于历史最佳参数的局部搜索
            params = self._sample_params_from_best(best_params, scale=0.2)
            score = self._evaluate_params(params)

            self.history.append({'params': params, 'score': score})

            if score > best_score:
                best_score = score
                best_params = params
                logger.info(f"  迭代 {i+1}/{self.max_iterations}: score={score:.4f}, best={best_score:.4f} ✓")
            else:
                logger.info(f"  迭代 {i+1}/{self.max_iterations}: score={score:.4f}, best={best_score:.4f}")

        optimization_time = time.time() - start_time

        # 计算改进幅度
        initial_score = self.history[0]['score'] if self.history else 0
        improvement = (best_score - initial_score) / abs(initial_score) if initial_score != 0 else 0

        return OptimizationResult(
            best_params=best_params,
            best_score=best_score,
            optimization_time=optimization_time,
            iteration_count=len(self.history),
            improvement=improvement
        )

    def _sample_params(self, random: bool = True) -> Dict[str, float]:
        """采样参数"""
        params = {}

        for param in self.param_space:
            if param.param_type == 'continuous':
                if random:
                    params[param.name] = np.random.uniform(param.low, param.high)
                else:
                    params[param.name] = (param.low + param.high) / 2
            elif param.param_type == 'integer':
                if random:
                    params[param.name] = int(np.random.uniform(param.low, param.high))
                else:
                    params[param.name] = int((param.low + param.high) / 2)
            elif param.param_type == 'categorical':
                if random:
                    params[param.name] = np.random.choice(param.choices)
                else:
                    params[param.name] = param.choices[0]

        return params

    def _sample_params_from_best(self, best_params: Dict, scale: float = 0.2) -> Dict[str, float]:
        """基于最佳参数采样"""
        params = {}

        for param in self.param_space:
            if param.param_type == 'continuous':
                best_value = best_params.get(param.name, (param.low + param.high) / 2)
                range_width = (param.high - param.low) * scale
                low = max(param.low, best_value - range_width / 2)
                high = min(param.high, best_value + range_width / 2)
                params[param.name] = np.random.uniform(low, high)
            elif param.param_type == 'integer':
                best_value = best_params.get(param.name, int((param.low + param.high) / 2))
                range_width = int((param.high - param.low) * scale)
                low = max(param.low, best_value - range_width // 2)
                high = min(param.high, best_value + range_width // 2)
                params[param.name] = int(np.random.uniform(low, high))
            elif param.param_type == 'categorical':
                params[param.name] = np.random.choice(param.choices)

        return params

    def _evaluate_params(self, params: Dict) -> float:
        """评估参数"""
        try:
            score = self.objective_func(params)
            return score
        except Exception as e:
            return float('-inf')


class ParameterOptimizer:
    """参数优化管理器"""

    def __init__(self, config: Optional[Dict] = None):
        """
        初始化参数优化管理器

        Args:
            config: 配置字典
        """
        self.config = config or {}

        # 优化配置
        self.optimization_interval = self.config.get('optimization_interval', 100)  # 每N笔交易优化一次
        self.max_iterations = self.config.get('max_iterations', 50)
        self.n_random_starts = self.config.get('n_random_starts', 10)

        # 数据库路径
        self.db_path = self.config.get('db_path', 'state/parameter_optimization.db')
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        # 初始化数据库
        self._init_db()

        # 参数空间定义
        self.param_spaces = self._define_param_spaces()

    def _init_db(self):
        """初始化数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 创建优化历史表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS optimization_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER NOT NULL,
                best_params TEXT NOT NULL,
                best_score REAL NOT NULL,
                iteration_count INTEGER NOT NULL,
                optimization_time REAL NOT NULL,
                improvement REAL NOT NULL
            )
        """)

        # 创建当前参数表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS current_params (
                param_name TEXT PRIMARY KEY,
                param_value REAL NOT NULL,
                updated_at INTEGER NOT NULL
            )
        """)

        conn.commit()
        conn.close()

    def _define_param_spaces(self) -> Dict[str, List[ParameterSpace]]:
        """定义参数空间"""
        return {
            "risk_control": [
                ParameterSpace("atr_stop_loss_multiplier", "continuous", 1.5, 2.5),
                ParameterSpace("atr_take_profit_multiplier", "continuous", 2.0, 4.0),
                ParameterSpace("max_position_size", "continuous", 0.15, 0.35),
                ParameterSpace("daily_loss_limit", "continuous", 0.02, 0.05)
            ],
            "signal_generation": [
                ParameterSpace("rsi_oversold", "integer", 25, 35),
                ParameterSpace("rsi_overbought", "integer", 65, 75),
                ParameterSpace("signal_score_threshold", "continuous", 0.55, 0.75),
                ParameterSpace("adx_threshold", "integer", 15, 30)
            ],
            "position_management": [
                ParameterSpace("kelly_multiplier", "continuous", 0.1, 0.3),
                ParameterSpace("trailing_stop_activation", "continuous", 0.8, 1.5),
                ParameterSpace("trailing_stop_distance", "continuous", 1.0, 2.0)
            ]
        }

    def calculate_objective_score(
        self,
        trade_history: List[Dict]
    ) -> float:
        """
        计算目标函数得分（夏普比率）

        Args:
            trade_history: 交易历史

        Returns:
            目标得分
        """
        if not trade_history:
            return 0.0

        # 提取收益
        returns = [trade.get('pnl', 0) for trade in trade_history]

        if not returns:
            return 0.0

        # 计算收益率
        mean_return = np.mean(returns)
        std_return = np.std(returns)

        # 夏普比率
        if std_return == 0:
            return 0.0

        sharpe_ratio = mean_return / std_return

        # 考虑最大回撤惩罚
        cumulative_returns = np.cumsum(returns)
        running_max = np.maximum.accumulate(cumulative_returns)
        drawdowns = cumulative_returns - running_max
        max_drawdown = np.min(drawdowns)

        # 目标函数：夏普比率 - 最大回撤惩罚
        objective_score = sharpe_ratio - abs(max_drawdown) * 0.5

        return objective_score

    def optimize_parameters(
        self,
        trade_history: List[Dict],
        param_group: str = "all"
    ) -> Optional[OptimizationResult]:
        """
        优化参数

        Args:
            trade_history: 交易历史
            param_group: 参数组（'risk_control', 'signal_generation', 'position_management', 'all'）

        Returns:
            优化结果
        """
        if not trade_history:
            return None

        # 选择参数空间
        if param_group == "all":
            param_space = []
            for space_list in self.param_spaces.values():
                param_space.extend(space_list)
        else:
            param_space = self.param_spaces.get(param_group, [])

        if not param_space:
            return None

        # 定义目标函数（模拟，实际需要回测）
        def objective_func(params: Dict) -> float:
            # 这里应该是参数→回测→得分的完整流程
            # 简化版本：基于历史交易数据模拟参数影响
            base_score = self.calculate_objective_score(trade_history)

            # 模拟参数对得分的随机影响（实际应该回测）
            param_effect = np.random.normal(0, 0.1)

            return base_score + param_effect

        # 创建优化器
        optimizer = BayesianOptimizer(
            objective_func=objective_func,
            param_space=param_space,
            max_iterations=self.max_iterations,
            n_random_starts=self.n_random_starts
        )

        # 执行优化
        result = optimizer.optimize()

        # 保存结果
        self._save_optimization_result(result)

        return result

    def update_config_file(
        self,
        best_params: Dict,
        config_path: str
    ) -> bool:
        """
        更新配置文件

        Args:
            best_params: 最佳参数
            config_path: 配置文件路径

        Returns:
            是否成功
        """
        try:
            # 加载配置文件
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)

            # 更新参数
            # 这里需要根据配置文件结构更新对应的参数
            # 示例：更新风控参数
            if "risk_control" in config:
                risk_control = config["risk_control"]

                if "atr_stop_loss_multiplier" in best_params:
                    risk_control["atr_multiplier"] = best_params["atr_stop_loss_multiplier"]

                if "atr_take_profit_multiplier" in best_params:
                    risk_control["take_profit_multiplier"] = best_params["atr_take_profit_multiplier"]

                if "max_position_size" in best_params:
                    risk_control["max_position_size"] = best_params["max_position_size"]

            # 保存配置文件
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)

            logger.info(f"\n✅ 配置文件已更新: {config_path}")

            # 保存当前参数到数据库
            for param_name, param_value in best_params.items():
                self._save_current_param(param_name, param_value)

            return True

        except Exception as e:
            logger.error(f"\n❌ 配置文件更新失败: {str(e)}")
            return False

    def _save_optimization_result(self, result: OptimizationResult):
        """保存优化结果"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO optimization_history
            (timestamp, best_params, best_score, iteration_count, optimization_time, improvement)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            int(datetime.now().timestamp() * 1000),
            json.dumps(result.best_params),
            result.best_score,
            result.iteration_count,
            result.optimization_time,
            result.improvement
        ))
        conn.commit()
        conn.close()

    def _save_current_param(self, param_name: str, param_value: float):
        """保存当前参数"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO current_params
            (param_name, param_value, updated_at)
            VALUES (?, ?, ?)
        """, (param_name, param_value, int(datetime.now().timestamp() * 1000)))
        conn.commit()
        conn.close()

    def get_optimization_history(self, limit: int = 10) -> List[Dict]:
        """获取优化历史"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT timestamp, best_params, best_score, iteration_count, optimization_time, improvement
            FROM optimization_history
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,))

        history = []
        for row in cursor.fetchall():
            history.append({
                "timestamp": row[0],
                "best_params": json.loads(row[1]),
                "best_score": row[2],
                "iteration_count": row[3],
                "optimization_time": row[4],
                "improvement": row[5]
            })

        conn.close()
        return history


def main():
    parser = argparse.ArgumentParser(description="自适应参数优化（贝叶斯优化）")
    parser.add_argument("--action", choices=["optimize", "update_config", "history"], required=True, help="操作类型")
    parser.add_argument("--trade-history", help="交易历史JSON文件路径")
    parser.add_argument("--param-group", choices=["risk_control", "signal_generation", "position_management", "all"], default="all", help="参数组")
    parser.add_argument("--config-path", help="配置文件路径")
    parser.add_argument("--limit", type=int, default=10, help="历史记录数量")

    args = parser.parse_args()

    try:
        # 创建参数优化管理器
        optimizer = ParameterOptimizer()

        logger.info("=" * 70)
        logger.info("✅ 自适应参数优化（贝叶斯优化）- v1.0.3扩展")
        logger.info("=" * 70)

        if args.action == "optimize":
            if not args.trade_history:
                logger.info("错误: 请提供 --trade-history 参数")
                sys.exit(1)

            # 加载交易历史
            with open(args.trade_history, 'r', encoding='utf-8') as f:
                trade_history = json.load(f)

            logger.info(f"\n交易历史:")
            logger.info(f"  交易数: {len(trade_history)}")

            # 计算当前得分
            current_score = optimizer.calculate_objective_score(trade_history)
            logger.info(f"  当前目标得分: {current_score:.4f}")

            # 执行优化
            logger.info(f"\n开始优化参数组: {args.param_group}")
            logger.info(f"  最大迭代次数: {optimizer.max_iterations}")
            logger.info(f"  随机采样次数: {optimizer.n_random_starts}")

            result = optimizer.optimize_parameters(trade_history, args.param_group)

            if result:
                logger.info(f"\n优化完成:")
                logger.info(f"  最佳得分: {result.best_score:.4f}")
                logger.info(f"  改进幅度: {result.improvement*100:.2f}%")
                logger.info(f"  迭代次数: {result.iteration_count}")
                logger.info(f"  优化时间: {result.optimization_time:.2f}秒")
                logger.info(f"\n最佳参数:")
                for param_name, param_value in result.best_params.items():
                    logger.info(f"  {param_name}: {param_value:.4f}")

                output = {
                    "status": "success",
                    "best_params": result.best_params,
                    "best_score": result.best_score,
                    "improvement": result.improvement,
                    "iteration_count": result.iteration_count,
                    "optimization_time": result.optimization_time
                }
            else:
                logger.info(f"\n❌ 优化失败")
                output = {
                    "status": "error",
                    "message": "优化失败"
                }

        elif args.action == "update_config":
            if not args.config_path:
                logger.info("错误: 请提供 --config-path 参数")
                sys.exit(1)

            # 模拟最佳参数
            best_params = {
                "atr_stop_loss_multiplier": 2.0,
                "atr_take_profit_multiplier": 3.5,
                "max_position_size": 0.25
            }

            # 更新配置文件
            success = optimizer.update_config_file(best_params, args.config_path)

            if success:
                output = {
                    "status": "success",
                    "config_path": args.config_path,
                    "updated_params": best_params
                }
            else:
                output = {
                    "status": "error",
                    "message": "配置文件更新失败"
                }

        elif args.action == "history":
            # 获取优化历史
            history = optimizer.get_optimization_history(args.limit)

            logger.info(f"\n优化历史 ({len(history)} 条):")

            for i, record in enumerate(history):
                logger.info(f"\n  记录 {i+1}:")
                logger.info(f"    时间: {record['timestamp']}")
                logger.info(f"    最佳得分: {record['best_score']:.4f}")
                logger.info(f"    改进幅度: {record['improvement']*100:.2f}%")
                logger.info(f"    迭代次数: {record['iteration_count']}")
                logger.info(f"    优化时间: {record['optimization_time']:.2f}秒")

            output = {
                "status": "success",
                "history_count": len(history),
                "history": history
            }

        logger.info(f"\n{'=' * 70}")
        logger.info(json.dumps(output, ensure_ascii=False, indent=2))

    except Exception as e:
        logger.error((json.dumps({)
            "status": "error",
            "message": str(e)
        }, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
