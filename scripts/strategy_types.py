#!/usr/bin/env python3
"""
策略个体类型定义 - v1.0.3 Integrated
打破循环依赖，提供统一的策略个体类型定义
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from enum import Enum
import numpy as np

# 导入统一的ActionType
from scripts.unified_models import ActionType


class IndicatorType(Enum):
    """技术指标类型"""
    SMA = "sma"
    EMA = "ema"
    RSI = "rsi"
    MACD = "macd"
    ATR = "atr"
    BOLLINGER = "bollinger"
    STOCHASTIC = "stochastic"
    VOLATILITY = "volatility"


class OperatorType(Enum):
    """操作符类型"""
    GT = ">"       # 大于
    LT = "<"       # 小于
    GTE = ">="     # 大于等于
    LTE = "<="     # 小于等于
    EQ = "=="      # 等于
    NEQ = "!="     # 不等于
    AND = "and"    # 逻辑与
    OR = "or"      # 逻辑或
    NOT = "not"    # 逻辑非


@dataclass
class StrategyIndividual:
    """策略个体（遗传编程中的单个策略）"""
    id: str
    genotype: List[Any]  # 基因型（表达式树）
    fitness: float = 0.0  # 适应度
    parameters: Dict[str, Any] = None  # 策略参数
    
    def __post_init__(self):
        if self.parameters is None:
            self.parameters = {}
    
    def evaluate(self, data: Dict[str, np.ndarray]) -> Optional[str]:
        """
        评估策略，返回信号
        
        Args:
            data: 包含OHLCV数据的字典
            
        Returns:
            信号类型 (BUY/SELL/HOLD) 或 None
        """
        # 简化版：基于随机适应度返回信号
        # 实际实现应该解析genotype并计算
        if self.fitness > 0.5:
            return ActionType.BUY.value
        elif self.fitness < 0.3:
            return ActionType.SELL.value
        else:
            return ActionType.HOLD.value
    
    def mutate(self, mutation_rate: float = 0.1):
        """
        变异操作
        
        Args:
            mutation_rate: 变异率
        """
        # 简化版：随机修改适应度
        import random
        if random.random() < mutation_rate:
            self.fitness += random.uniform(-0.1, 0.1)
            self.fitness = max(0.0, min(1.0, self.fitness))
    
    def crossover(self, other: 'StrategyIndividual') -> 'StrategyIndividual':
        """
        交叉操作
        
        Args:
            other: 另一个个体
            
        Returns:
            新个体
        """
        # 简化版：平均适应度
        new_fitness = (self.fitness + other.fitness) / 2
        return StrategyIndividual(
            id=f"child_{self.id}_{other.id}",
            genotype=self.genotype[:len(self.genotype)//2] + other.genotype[len(other.genotype)//2:],
            fitness=new_fitness,
            parameters=self.parameters.copy()
        )


if __name__ == "__main__":
    # 测试
    print("测试策略个体类型定义...")
    
    individual = StrategyIndividual(
        id="test_001",
        genotype=[IndicatorType.SMA, OperatorType.GT, IndicatorType.EMA],
        fitness=0.7
    )
    
    print(f"个体ID: {individual.id}")
    print(f"适应度: {individual.fitness}")
    print(f"信号: {individual.evaluate({})}")
    
    print("\n✅ 测试通过")
