#!/usr/bin/env python3
"""
策略实验室 - Phase 6 核心组件
使用遗传编程自动发现交易策略
"""

import random
import numpy as np
from typing import List, Dict, Tuple, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
import time
import json

try:
    from scripts.logger_factory import get_logger
    logger = get_logger("strategy_lab")
except ImportError:
    import logging
    logger = logging.getLogger("strategy_lab")

# 导入历史数据加载器和回测适配器
try:
    from scripts.historical_data_loader import HistoricalDataLoader, DataSpec, DataSource, DataFrequency
    from scripts.backtest_adapter import BacktestAdapter
    from scripts.unified_models import ActionType  # 统一模型定义
except ImportError:
    logger.warning("无法导入数据加载器或回测适配器，将使用模拟模式")
    HistoricalDataLoader = None
    DataSpec = None
    DataSource = None
    ActionType = None
    DataFrequency = None
    BacktestAdapter = None

# 动态创建ActionType备用枚举（当导入失败时）
if ActionType is None:
    from enum import Enum as _Enum
    ActionType = _Enum("ActionType", ["BUY", "SELL", "HOLD"])
    logger.info("已创建备用ActionType枚举")


class IndicatorType(Enum):
    """技术指标类型"""
    SMA = "sma"
    EMA = "ema"
    RSI = "rsi"
    MACD = "macd"
    BOLLINGER = "bollinger"
    ATR = "atr"
    VWAP = "vwap"
    MOMENTUM = "momentum"
    VOLUME = "volume"


class OperatorType(Enum):
    """操作符类型"""
    GREATER_THAN = ">"
    LESS_THAN = "<"
    GREATER_EQUAL = ">="
    LESS_EQUAL = "<="
    EQUAL = "=="
    AND = "and"
    OR = "or"
    CROSS_OVER = "cross_over"
    CROSS_UNDER = "cross_under"


@dataclass
class StrategyGene:
    """策略基因"""
    indicator1: IndicatorType
    indicator2: Optional[IndicatorType] = None  # 用于交叉比较
    operator: OperatorType = OperatorType.GREATER_THAN
    threshold: float = 0.0
    period: int = 20  # 周期参数
    action: ActionType = ActionType.BUY

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            'indicator1': self.indicator1.value,
            'indicator2': self.indicator2.value if self.indicator2 else None,
            'operator': self.operator.value,
            'threshold': self.threshold,
            'period': self.period,
            'action': self.action.value
        }


@dataclass
class StrategyIndividual:
    """策略个体（完整策略）"""
    genes: List[StrategyGene] = field(default_factory=list)
    fitness: float = 0.0
    sharpe_ratio: float = 0.0
    win_rate: float = 0.0
    max_drawdown: float = 0.0
    total_return: float = 0.0

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            'genes': [gene.to_dict() for gene in self.genes],
            'fitness': self.fitness,
            'sharpe_ratio': self.sharpe_ratio,
            'win_rate': self.win_rate,
            'max_drawdown': self.max_drawdown,
            'total_return': self.total_return
        }


class StrategyLab:
    """策略实验室 - 遗传编程框架"""

    def __init__(self,
                 population_size: int = 100,
                 generations: int = 50,
                 mutation_rate: float = 0.1,
                 crossover_rate: float = 0.7,
                 elite_size: int = 10,
                 use_backtest_adapter: bool = True):
        """
        初始化策略实验室

        Args:
            population_size: 种群大小
            generations: 迭代代数
            mutation_rate: 变异率
            crossover_rate: 交叉率
            elite_size: 精英保留数量
            use_backtest_adapter: 是否使用回测适配器
        """
        self.population_size = population_size
        self.generations = generations
        self.mutation_rate = mutation_rate
        self.crossover_rate = crossover_rate
        self.elite_size = elite_size
        self.use_backtest_adapter = use_backtest_adapter

        self.population: List[StrategyIndividual] = []
        self.best_individual: Optional[StrategyIndividual] = None
        self.history: List[Dict] = []

        # 初始化数据加载器和回测适配器
        self.data_loader = None
        self.backtest_adapter = None

        if use_backtest_adapter and HistoricalDataLoader and BacktestAdapter:
            self.data_loader = HistoricalDataLoader()
            self.backtest_adapter = BacktestAdapter()
            logger.info("策略实验室已启用回测适配器")

    def initialize_population(self) -> None:
        """初始化种群"""
        self.population = []
        for _ in range(self.population_size):
            individual = self._create_random_individual()
            self.population.append(individual)

        logger.info(f"种群初始化完成: {self.population_size} 个个体")

    def _create_random_individual(self) -> StrategyIndividual:
        """创建随机个体"""
        gene_count = random.randint(1, 5)  # 1-5个基因
        genes = []

        for _ in range(gene_count):
            indicator1 = random.choice(list(IndicatorType))

            # 随机决定是否使用交叉比较
            if random.random() < 0.3:  # 30%概率使用交叉
                indicator2 = random.choice([i for i in list(IndicatorType) if i != indicator1])
                operator = random.choice([OperatorType.CROSS_OVER, OperatorType.CROSS_UNDER])
            else:
                indicator2 = None
                operator = random.choice([
                    OperatorType.GREATER_THAN,
                    OperatorType.LESS_THAN,
                    OperatorType.GREATER_EQUAL,
                    OperatorType.LESS_EQUAL
                ])

            threshold = random.uniform(-1.0, 1.0)
            period = random.randint(5, 50)
            action = random.choice([ActionType.BUY, ActionType.SELL])

            gene = StrategyGene(
                indicator1=indicator1,
                indicator2=indicator2,
                operator=operator,
                threshold=threshold,
                period=period,
                action=action
            )
            genes.append(gene)

        return StrategyIndividual(genes=genes)

    def evaluate_population(self, market_data: np.ndarray = None, data_spec: DataSpec = None) -> None:
        """
        评估种群适应度

        Args:
            market_data: 市场数据 (OHLCV格式)，优先使用
            data_spec: 数据规格，当market_data为None时使用
        """
        # 第一层防御：加载数据
        if market_data is None:
            if self.data_loader and data_spec:
                market_data = self.data_loader.load(data_spec)
                if market_data.shape[0] < 100:
                    logger.error(f"加载数据不足: {market_data.shape[0]}")
                    return
            else:
                # 使用模拟数据（向后兼容）
                np.random.seed(42)
                n_samples = 1000
                market_data = np.random.randn(n_samples, 5) * 0.01
                market_data[:, 3] = np.cumsum(market_data[:, 3]) + 100
                logger.warning("使用模拟数据进行评估")

        for individual in self.population:
            try:
                # 第二层防御：回测评估
                if self.backtest_adapter:
                    result = self.backtest_adapter.run_backtest(individual, market_data)

                    individual.fitness = result.sharpe_ratio * 0.5 + \
                                        result.win_rate * 0.3 - \
                                        result.max_drawdown * 2.0 + \
                                        result.total_return * 0.2

                    individual.sharpe_ratio = result.sharpe_ratio
                    individual.win_rate = result.win_rate
                    individual.max_drawdown = result.max_drawdown
                    individual.total_return = result.total_return
                else:
                    # 第三层防御：简化评估（向后兼容）
                    metrics = self._backtest_strategy(individual, market_data)
                    individual.fitness = self._calculate_fitness(metrics)
                    individual.sharpe_ratio = metrics.get('sharpe_ratio', 0.0)
                    individual.win_rate = metrics.get('win_rate', 0.0)
                    individual.max_drawdown = metrics.get('max_drawdown', 0.0)
                    individual.total_return = metrics.get('total_return', 0.0)

            except Exception as e:
                logger.warning(f"个体评估异常: {e}")
                individual.fitness = -999.0

        # 记录最佳个体
        self.population.sort(key=lambda x: x.fitness, reverse=True)
        if not self.best_individual or self.population[0].fitness > self.best_individual.fitness:
            self.best_individual = self.population[0]
            logger.info(f"发现新最佳个体: fitness={self.best_individual.fitness:.4f}, "
                       f"sharpe={self.best_individual.sharpe_ratio:.4f}")

    def _backtest_strategy(self, individual: StrategyIndividual, market_data: np.ndarray) -> Dict:
        """
        模拟回测单个策略

        Args:
            individual: 策略个体
            market_data: 市场数据

        Returns:
            回测指标字典
        """
        # 简化的回测逻辑
        # 实际实现需要完整的技术指标计算和交易逻辑

        signals = []
        for i in range(100, len(market_data)):  # 跳过前100根K线
            close = market_data[i, 3]  # 收盘价
            signal = self._generate_signal(individual, market_data[:i+1])
            signals.append(signal)

        # 计算简单指标
        if not signals:
            return {'sharpe_ratio': 0.0, 'win_rate': 0.0, 'max_drawdown': 0.0, 'total_return': 0.0}

        # 模拟盈亏
        total_return = sum(s.value for s in signals) * 0.01  # 简化计算
        win_count = sum(1 for s in signals if s.value > 0)
        win_rate = win_count / len(signals) if signals else 0.0

        # Sharpe比率（简化）
        sharpe_ratio = total_return / max(0.01, np.std([s.value for s in signals]))

        # 最大回撤（简化）
        max_drawdown = abs(min(0.0, total_return * 0.5))

        return {
            'sharpe_ratio': sharpe_ratio,
            'win_rate': win_rate,
            'max_drawdown': max_drawdown,
            'total_return': total_return
        }

    def _generate_signal(self, individual: StrategyIndividual, market_data: np.ndarray) -> 'Signal':
        """生成交易信号"""
        # 简化实现：返回随机信号
        value = random.uniform(-0.5, 0.5)
        return Signal(action=ActionType.BUY if value > 0 else ActionType.SELL, value=value)

    def _calculate_fitness(self, metrics: Dict) -> float:
        """
        计算适应度

        Args:
            metrics: 回测指标

        Returns:
            适应度分数
        """
        # 第一层防御：参数校验
        sharpe = metrics.get('sharpe_ratio', 0.0)
        win_rate = metrics.get('win_rate', 0.0)
        max_dd = metrics.get('max_drawdown', 0.0)
        total_return = metrics.get('total_return', 0.0)

        # 第二层防御：除零保护
        max_dd = max(0.01, max_dd)

        # 综合适应度函数
        # fitness = Sharpe + WinRate - Drawdown_Penalty + Return
        fitness = sharpe * 0.5 + win_rate * 0.3 - max_dd * 2.0 + total_return * 0.2

        return max(-100.0, fitness)

    def selection(self) -> List[StrategyIndividual]:
        """选择操作（锦标赛选择）"""
        selected = []
        tournament_size = 5

        for _ in range(self.population_size - self.elite_size):
            # 锦标赛选择
            tournament = random.sample(self.population, tournament_size)
            winner = max(tournament, key=lambda x: x.fitness)
            selected.append(winner)

        return selected

    def crossover(self, parent1: StrategyIndividual, parent2: StrategyIndividual) -> Tuple[StrategyIndividual, StrategyIndividual]:
        """交叉操作（单点交叉）"""
        # 单点交叉
        if len(parent1.genes) == 0 or len(parent2.genes) == 0:
            return parent1, parent2

        crossover_point = random.randint(0, min(len(parent1.genes), len(parent2.genes)))

        child1_genes = parent1.genes[:crossover_point] + parent2.genes[crossover_point:]
        child2_genes = parent2.genes[:crossover_point] + parent1.genes[crossover_point:]

        child1 = StrategyIndividual(genes=child1_genes.copy())
        child2 = StrategyIndividual(genes=child2_genes.copy())

        return child1, child2

    def mutation(self, individual: StrategyIndividual) -> StrategyIndividual:
        """变异操作"""
        mutated = StrategyIndividual(genes=individual.genes.copy())

        for gene in mutated.genes:
            if random.random() < self.mutation_rate:
                # 随机变异
                mutation_type = random.choice(['operator', 'threshold', 'period', 'action'])

                if mutation_type == 'operator':
                    gene.operator = random.choice(list(OperatorType))
                elif mutation_type == 'threshold':
                    gene.threshold += random.uniform(-0.1, 0.1)
                    gene.threshold = max(-1.0, min(1.0, gene.threshold))
                elif mutation_type == 'period':
                    gene.period += random.randint(-5, 5)
                    gene.period = max(5, min(50, gene.period))
                elif mutation_type == 'action':
                    gene.action = random.choice([ActionType.BUY, ActionType.SELL])

        return mutated

    def evolve(self, market_data: np.ndarray) -> None:
        """
        进化一代

        Args:
            market_data: 市场数据
        """
        # 评估当前种群
        self.evaluate_population(market_data)

        # 选择
        selected = self.selection()

        # 交叉
        offspring = []
        for i in range(0, len(selected), 2):
            if i + 1 < len(selected) and random.random() < self.crossover_rate:
                child1, child2 = self.crossover(selected[i], selected[i + 1])
                offspring.extend([child1, child2])
            else:
                offspring.extend([selected[i]])

        # 变异
        mutated_offspring = [self.mutation(ind) for ind in offspring]

        # 精英保留 + 新一代
        elite = self.population[:self.elite_size]

        # 填充到种群大小
        while len(elite) + len(mutated_offspring) > self.population_size:
            mutated_offspring.pop()

        self.population = elite + mutated_offspring

        # 记录历史
        generation_stats = {
            'generation': len(self.history) + 1,
            'best_fitness': self.best_individual.fitness,
            'best_sharpe': self.best_individual.sharpe_ratio,
            'avg_fitness': np.mean([ind.fitness for ind in self.population])
        }
        self.history.append(generation_stats)

        logger.info(f"第{generation_stats['generation']}代完成: "
                   f"best_fitness={generation_stats['best_fitness']:.4f}, "
                   f"avg_fitness={generation_stats['avg_fitness']:.4f}")

    def run(self, market_data: np.ndarray) -> StrategyIndividual:
        """
        运行完整进化过程

        Args:
            market_data: 市场数据

        Returns:
            最佳策略个体
        """
        logger.info(f"开始策略进化: population={self.population_size}, generations={self.generations}")

        # 初始化种群
        self.initialize_population()

        # 迭代进化
        for gen in range(self.generations):
            self.evolve(market_data)

        # 最终评估
        self.evaluate_population(market_data)

        logger.info(f"策略进化完成: best_fitness={self.best_individual.fitness:.4f}, "
                   f"sharpe={self.best_individual.sharpe_ratio:.4f}, "
                   f"win_rate={self.best_individual.win_rate:.4f}")

        return self.best_individual


class Signal:
    """交易信号"""
    def __init__(self, action: ActionType, value: float):
        self.action = action
        self.value = value


if __name__ == "__main__":
    # 测试代码
    # 生成模拟市场数据
    np.random.seed(42)
    n_samples = 1000
    market_data = np.random.randn(n_samples, 5) * 0.01  # OHLCV
    market_data[:, 3] = np.cumsum(market_data[:, 3]) + 100  # 价格累积

    # 运行策略实验室
    lab = StrategyLab(
        population_size=50,
        generations=20,
        mutation_rate=0.1,
        crossover_rate=0.7,
        elite_size=5
    )

    best_strategy = lab.run(market_data)

    print(f"\n最佳策略:")
    print(json.dumps(best_strategy.to_dict(), indent=2, ensure_ascii=False))
