#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("information_aggregator")
except ImportError:
    import logging
    logger = logging.getLogger("information_aggregator")
"""
信息聚合系统（第9层：汇总信息）
数据聚合系统 + 知识图谱
"""

import argparse
import json
import sys
import time
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from enum import Enum
import numpy as np
from collections import defaultdict
import hashlib


class DataType(Enum):
    """数据类型"""
    MARKET_DATA = "MARKET_DATA"  # 市场数据
    TRADE_DATA = "TRADE_DATA"  # 交易数据
    ANALYSIS_DATA = "ANALYSIS_DATA"  # 分析数据
    PERFORMANCE_DATA = "PERFORMANCE_DATA"  # 绩效数据
    EXPERIENCE_DATA = "EXPERIENCE_DATA"  # 经验数据
    SYSTEM_DATA = "SYSTEM_DATA"  # 系统数据


@dataclass
class DataPoint:
    """数据点"""
    data_id: str
    data_type: DataType
    content: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    source: str = ""
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            'data_id': self.data_id,
            'data_type': self.data_type.value,
            'content': self.content,
            'timestamp': self.timestamp,
            'source': self.source,
            'tags': self.tags,
            'metadata': self.metadata
        }


@dataclass
class KnowledgeNode:
    """知识节点"""
    node_id: str
    node_type: str
    content: Dict[str, Any]
    relationships: Dict[str, Set[str]] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_relationship(self, relation_type: str, target_node_id: str):
        """添加关系"""
        if relation_type not in self.relationships:
            self.relationships[relation_type] = set()
        self.relationships[relation_type].add(target_node_id)

    def to_dict(self) -> Dict:
        return {
            'node_id': self.node_id,
            'node_type': self.node_type,
            'content': self.content,
            'relationships': {k: list(v) for k, v in self.relationships.items()},
            'metadata': self.metadata
        }


class DataAggregator:
    """数据聚合器"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.max_data_points = self.config.get('max_data_points', 100000)

        self.data_points: Dict[str, DataPoint] = {}
        self.data_index: Dict[str, Set[str]] = defaultdict(set)  # tag -> data_ids
        self.data_type_index: Dict[DataType, Set[str]] = defaultdict(set)

    def add_data(self, data_point: DataPoint):
        """添加数据"""
        self.data_points[data_point.data_id] = data_point

        # 建立标签索引
        for tag in data_point.tags:
            self.data_index[tag].add(data_point.data_id)

        # 建立类型索引
        self.data_type_index[data_point.data_type].add(data_point.data_id)

        # 限制数量
        if len(self.data_points) > self.max_data_points:
            # 删除最旧的数据
            oldest_id = min(self.data_points.items(), key=lambda x: x[1].timestamp)[0]
            self.remove_data(oldest_id)

    def remove_data(self, data_id: str):
        """移除数据"""
        if data_id in self.data_points:
            data_point = self.data_points[data_id]

            # 从索引中移除
            for tag in data_point.tags:
                if tag in self.data_index:
                    self.data_index[tag].discard(data_id)

            if data_point.data_type in self.data_type_index:
                self.data_type_index[data_point.data_type].discard(data_id)

            del self.data_points[data_id]

    def get_data_by_type(self, data_type: DataType, limit: int = 100) -> List[DataPoint]:
        """按类型获取数据"""
        data_ids = list(self.data_type_index.get(data_type, set()))

        # 按时间倒序排序
        sorted_ids = sorted(
            data_ids,
            key=lambda x: self.data_points[x].timestamp,
            reverse=True
        )

        return [self.data_points[data_id] for data_id in sorted_ids[:limit]]

    def get_data_by_tag(self, tag: str, limit: int = 100) -> List[DataPoint]:
        """按标签获取数据"""
        data_ids = list(self.data_index.get(tag, set()))

        # 按时间倒序排序
        sorted_ids = sorted(
            data_ids,
            key=lambda x: self.data_points[x].timestamp,
            reverse=True
        )

        return [self.data_points[data_id] for data_id in sorted_ids[:limit]]

    def get_data_by_time_range(self, start_time: float, end_time: float) -> List[DataPoint]:
        """按时间范围获取数据"""
        return [
            data_point for data_point in self.data_points.values()
            if start_time <= data_point.timestamp <= end_time
        ]

    def aggregate_market_data(self, symbol: str, timeframe: str) -> Dict[str, Any]:
        """聚合市场数据"""
        # 获取相关市场数据
        relevant_data = self.get_data_by_tag(f"{symbol}_{timeframe}")

        if not relevant_data:
            return {}

        # 简化聚合：取最新数据
        latest_data = relevant_data[0].content

        # 计算统计信息
        prices = [dp.content.get('close', 0) for dp in relevant_data if dp.content.get('close')]
        volumes = [dp.content.get('volume', 0) for dp in relevant_data if dp.content.get('volume')]

        aggregation = {
            'symbol': symbol,
            'timeframe': timeframe,
            'latest_price': latest_data.get('close', 0),
            'latest_volume': latest_data.get('volume', 0),
            'avg_price': np.mean(prices) if prices else 0,
            'price_std': np.std(prices) if len(prices) > 1 else 0,
            'total_volume': sum(volumes) if volumes else 0,
            'data_points_count': len(relevant_data)
        }

        return aggregation

    def aggregate_trade_data(self, symbol: str) -> Dict[str, Any]:
        """聚合交易数据"""
        # 获取相关交易数据
        relevant_data = self.get_data_by_tag(symbol)

        if not relevant_data:
            return {}

        trades = []
        for data_point in relevant_data:
            if data_point.data_type == DataType.TRADE_DATA:
                trades.append(data_point.content)

        if not trades:
            return {}

        # 计算统计信息
        total_trades = len(trades)
        winning_trades = [t for t in trades if t.get('pnl', 0) > 0]
        losing_trades = [t for t in trades if t.get('pnl', 0) <= 0]

        win_rate = len(winning_trades) / total_trades if total_trades > 0 else 0
        total_pnl = sum(t.get('pnl', 0) for t in trades)
        avg_pnl = total_pnl / total_trades if total_trades > 0 else 0

        aggregation = {
            'symbol': symbol,
            'total_trades': total_trades,
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'avg_pnl': avg_pnl
        }

        return aggregation

    def get_summary(self) -> Dict[str, Any]:
        """获取摘要"""
        summary = {
            'total_data_points': len(self.data_points),
            'by_type': {},
            'top_tags': []
        }

        # 按类型统计
        for data_type, data_ids in self.data_type_index.items():
            summary['by_type'][data_type.value] = len(data_ids)

        # 标签统计
        tag_counts = [(tag, len(ids)) for tag, ids in self.data_index.items()]
        tag_counts.sort(key=lambda x: x[1], reverse=True)
        summary['top_tags'] = tag_counts[:20]

        return summary


class KnowledgeGraph:
    """知识图谱"""

    def __init__(self):
        self.nodes: Dict[str, KnowledgeNode] = {}
        self.node_index: Dict[str, Set[str]] = defaultdict(set)  # node_type -> node_ids

    def add_node(self, node: KnowledgeNode):
        """添加节点"""
        self.nodes[node.node_id] = node
        self.node_index[node.node_type].add(node.node_id)

    def get_node(self, node_id: str) -> Optional[KnowledgeNode]:
        """获取节点"""
        return self.nodes.get(node_id)

    def get_nodes_by_type(self, node_type: str) -> List[KnowledgeNode]:
        """按类型获取节点"""
        return [self.nodes[node_id] for node_id in self.node_index.get(node_type, set())]

    def create_relationship(self, source_id: str, target_id: str, relation_type: str):
        """创建关系"""
        source_node = self.nodes.get(source_id)
        target_node = self.nodes.get(target_id)

        if source_node and target_node:
            source_node.add_relationship(relation_type, target_id)

    def get_related_nodes(self, node_id: str, relation_type: str, max_depth: int = 1) -> List[KnowledgeNode]:
        """获取相关节点"""
        if max_depth < 1:
            return []

        node = self.nodes.get(node_id)
        if not node:
            return []

        related = []

        # 直接关系
        target_ids = node.relationships.get(relation_type, set())
        for target_id in target_ids:
            related.append(self.nodes.get(target_id))

            # 递归获取
            if max_depth > 1:
                related.extend(self.get_related_nodes(target_id, relation_type, max_depth - 1))

        return [n for n in related if n is not None]

    def build_from_trades(self, trades: List[Dict]):
        """从交易数据构建知识图谱"""
        for trade in trades:
            # 创建交易节点
            trade_node = KnowledgeNode(
                node_id=f"trade_{trade.get('trade_id', '')}",
                node_type='trade',
                content=trade
            )

            self.add_node(trade_node)

            # 创建品种节点
            symbol = trade.get('symbol', '')
            symbol_node = KnowledgeNode(
                node_id=f"symbol_{symbol}",
                node_type='symbol',
                content={'symbol': symbol}
            )

            if symbol_node.node_id not in self.nodes:
                self.add_node(symbol_node)

            # 创建关系
            self.create_relationship(trade_node.node_id, symbol_node.node_id, 'about')

            # 创建策略节点
            strategy = trade.get('strategy', '')
            if strategy:
                strategy_node = KnowledgeNode(
                    node_id=f"strategy_{strategy}",
                    node_type='strategy',
                    content={'strategy': strategy}
                )

                if strategy_node.node_id not in self.nodes:
                    self.add_node(strategy_node)

                self.create_relationship(trade_node.node_id, strategy_node.node_id, 'uses')

    def query(self, query_type: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """查询知识图谱"""
        results = []

        if query_type == 'symbol_performance':
            # 查询品种绩效
            symbol = params.get('symbol')
            symbol_node = self.nodes.get(f"symbol_{symbol}")

            if symbol_node:
                # 获取该品种的所有交易
                trade_nodes = self.get_related_nodes(symbol_node.node_id, 'about')

                total_trades = len(trade_nodes)
                winning_trades = [t for t in trade_nodes if t.content.get('pnl', 0) > 0]

                results.append({
                    'symbol': symbol,
                    'total_trades': total_trades,
                    'win_rate': len(winning_trades) / total_trades if total_trades > 0 else 0
                })

        elif query_type == 'strategy_usage':
            # 查询策略使用情况
            strategy_nodes = self.get_nodes_by_type('strategy')

            for strategy_node in strategy_nodes:
                strategy = strategy_node.content.get('strategy', '')

                # 获取使用该策略的交易
                trade_nodes = self.get_related_nodes(strategy_node.node_id, 'uses')

                results.append({
                    'strategy': strategy,
                    'usage_count': len(trade_nodes)
                })

        return results

    def get_summary(self) -> Dict[str, Any]:
        """获取摘要"""
        return {
            'total_nodes': len(self.nodes),
            'by_type': {node_type: len(node_ids) for node_type, node_ids in self.node_index.items()}
        }


class InformationAggregator:
    """信息聚合系统"""

    def __init__(self, config: Optional[Dict] = None):
        """
        初始化信息聚合系统

        Args:
            config: 配置字典
        """
        self.config = config or {}

        self.data_aggregator = DataAggregator(self.config.get('data_config', {}))
        self.knowledge_graph = KnowledgeGraph()

    def aggregate(self, data_point: DataPoint):
        """聚合数据"""
        self.data_aggregator.add_data(data_point)

    def build_knowledge_graph(self):
        """构建知识图谱"""
        # 从交易数据构建
        trade_data = self.data_aggregator.get_data_by_type(DataType.TRADE_DATA)

        trades = [dp.content for dp in trade_data]
        self.knowledge_graph.build_from_trades(trades)

    def query(self, query_type: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """查询"""
        return self.knowledge_graph.query(query_type, params)

    def get_market_summary(self, symbol: str, timeframe: str) -> Dict[str, Any]:
        """获取市场摘要"""
        return self.data_aggregator.aggregate_market_data(symbol, timeframe)

    def get_trade_summary(self, symbol: str) -> Dict[str, Any]:
        """获取交易摘要"""
        return self.data_aggregator.aggregate_trade_data(symbol)

    def get_aggregation_summary(self) -> Dict[str, Any]:
        """获取聚合摘要"""
        data_summary = self.data_aggregator.get_summary()
        graph_summary = self.knowledge_graph.get_summary()

        return {
            'data_summary': data_summary,
            'graph_summary': graph_summary
        }


def main():
    parser = argparse.ArgumentParser(description="信息聚合系统（第9层：汇总信息）")
    parser.add_argument("--action", choices=["aggregate", "query", "summary", "test"], default="test", help="操作类型")
    parser.add_argument("--data", help="数据JSON")
    parser.add_argument("--query_type", help="查询类型")
    parser.add_argument("--params", help="查询参数JSON")
    parser.add_argument("--config", help="配置文件路径")

    args = parser.parse_args()

    try:
        # 加载配置
        config = {}
        if args.config:
            with open(args.config, 'r') as f:
                config = json.load(config)

        # 创建信息聚合系统
        aggregator = InformationAggregator(config)

        logger.info("=" * 70)
        logger.info("✅ 杀手锏交易系统 - 信息聚合系统（第9层：汇总信息）")
        logger.info("=" * 70)

        if args.action == "aggregate":
            # 聚合数据
            if not args.data:
                logger.info("错误: 请提供数据")
                sys.exit(1)

            data_content = json.loads(args.data)

            data_type_str = data_content.get('data_type', 'MARKET_DATA')
            data_type = DataType[data_type_str]

            data_point = DataPoint(
                data_id=data_content.get('data_id', f"data_{int(time.time())}"),
                data_type=data_type,
                content=data_content.get('content', {}),
                source=data_content.get('source', ''),
                tags=data_content.get('tags', [])
            )

            aggregator.aggregate(data_point)

            output = {
                "status": "success",
                "message": "数据已聚合",
                "data_id": data_point.data_id
            }

        elif args.action == "query":
            # 查询
            if not args.query_type:
                logger.info("错误: 请指定查询类型")
                sys.exit(1)

            params = json.loads(args.params) if args.params else {}

            results = aggregator.query(args.query_type, params)

            output = {
                "status": "success",
                "query_type": args.query_type,
                "params": params,
                "results": results
            }

        elif args.action == "summary":
            # 摘要
            summary = aggregator.get_aggregation_summary()

            output = {
                "status": "success",
                "summary": summary
            }

        elif args.action == "test":
            # 测试模式
            # 添加测试数据
            for i in range(10):
                # 市场数据
                market_data = DataPoint(
                    data_id=f"market_{i}",
                    data_type=DataType.MARKET_DATA,
                    content={
                        'symbol': 'BTCUSDT',
                        'timeframe': '1h',
                        'close': 50000.0 + np.random.uniform(-100, 100),
                        'volume': 1000.0
                    },
                    source='binance',
                    tags=['BTCUSDT', '1h', 'market']
                )

                aggregator.aggregate(market_data)

                # 交易数据
                trade_data = DataPoint(
                    data_id=f"trade_{i}",
                    data_type=DataType.TRADE_DATA,
                    content={
                        'trade_id': f'trade_{i}',
                        'symbol': 'BTCUSDT',
                        'side': 'LONG' if np.random.random() > 0.5 else 'SHORT',
                        'pnl': np.random.uniform(-500, 1000),
                        'strategy': 'trend_following' if i % 2 == 0 else 'mean_reversion'
                    },
                    source='system',
                    tags=['BTCUSDT', 'trade']
                )

                aggregator.aggregate(trade_data)

            # 构建知识图谱
            aggregator.build_knowledge_graph()

            # 测试查询
            symbol_query = aggregator.query('symbol_performance', {'symbol': 'BTCUSDT'})
            strategy_query = aggregator.query('strategy_usage', {})

            # 获取摘要
            market_summary = aggregator.get_market_summary('BTCUSDT', '1h')
            trade_summary = aggregator.get_trade_summary('BTCUSDT')
            aggregation_summary = aggregator.get_aggregation_summary()

            output = {
                "status": "success",
                "test_query_symbol_performance": symbol_query,
                "test_query_strategy_usage": strategy_query,
                "test_market_summary": market_summary,
                "test_trade_summary": trade_summary,
                "test_aggregation_summary": aggregation_summary
            }

        logger.info(f"\n{'=' * 70}")
        logger.info(json.dumps(output, ensure_ascii=False, indent=2))

    except Exception as e:
        import traceback
        logger.error((json.dumps({)
            "status": "error",
            "message": str(e),
            "traceback": traceback.format_exc()
        }, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
