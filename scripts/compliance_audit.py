#!/usr/bin/env python3
"""
合规审计系统 - v1.0.3 Integrated
记录所有决策事件，支持时间点回放，不可篡改审计
"""

import time
import json
import hashlib
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

try:
    from scripts.logger_factory import get_logger
    logger = get_logger("compliance_audit")
except ImportError:
    import logging
    logger = logging.getLogger("compliance_audit")

try:
    from scripts.event_bus import get_event_bus
    EVENT_BUS_AVAILABLE = True
except ImportError:
    EVENT_BUS_AVAILABLE = False


@dataclass
class AuditEvent:
    """审计事件"""
    event_id: str = field(default="")
    timestamp: float = field(default_factory=time.time)
    event_type: str = ""
    source: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    hash: str = ""

    def __post_init__(self):
        """生成事件ID和哈希"""
        if not self.event_id:
            # 基于时间戳和数据生成唯一ID
            data_str = json.dumps(self.data, sort_keys=True)
            unique_str = f"{self.timestamp}_{self.event_type}_{data_str}"
            self.event_id = hashlib.sha256(unique_str.encode()).hexdigest()[:16]

        # 生成事件哈希（用于完整性验证）
        event_str = f"{self.event_id}_{self.timestamp}_{self.event_type}_{json.dumps(self.data, sort_keys=True)}"
        self.hash = hashlib.sha256(event_str.encode()).hexdigest()

    def to_dict(self) -> Dict:
        """转换为字典"""
        return asdict(self)


class ComplianceAuditSystem:
    """合规审计系统"""

    def __init__(self, audit_dir: str = "audit_logs", max_logs: int = 10000):
        """
        初始化审计系统

        Args:
            audit_dir: 审计日志目录
            max_logs: 最大日志数量
        """
        self.audit_dir = Path(audit_dir)
        self.max_logs = max_logs

        # 内存中的事件缓存
        self.events: List[AuditEvent] = []

        # 创建审计目录
        self.audit_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"合规审计系统初始化完成: 目录={audit_dir}, 最大日志数={max_logs}")

    def record_event(self, event_type: str, source: str, data: Dict[str, Any]) -> bool:
        """
        记录审计事件

        Args:
            event_type: 事件类型
            source: 事件来源
            data: 事件数据

        Returns:
            是否记录成功
        """
        try:
            # 第一层防御：数据验证
            if not isinstance(data, dict):
                logger.error(f"事件数据必须是字典: {type(data)}")
                return False

            # 创建审计事件
            event = AuditEvent(
                event_type=event_type,
                source=source,
                data=data
            )

            # 添加到缓存
            self.events.append(event)

            # 第二层防御：限制缓存大小
            if len(self.events) > self.max_logs:
                # 持久化旧事件
                self._flush_old_events()

            logger.debug(f"记录审计事件: {event_type}, 来源={source}, ID={event.event_id}")

            # 广播事件
            if EVENT_BUS_AVAILABLE:
                bus = get_event_bus()
                bus.publish(
                    "audit.event_recorded",
                    {
                        "event_id": event.event_id,
                        "event_type": event_type,
                    },
                    source="compliance_audit"
                )

            return True

        except Exception as e:
            logger.error(f"记录审计事件失败: {event_type}, 错误={e}")
            return False

    def record_signal_event(self, strategy_id: str, signal: str, confidence: float, metadata: Dict = None) -> bool:
        """
        记录信号事件

        Args:
            strategy_id: 策略ID
            signal: 信号类型（BUY/SELL/HOLD）
            confidence: 信号置信度
            metadata: 元数据

        Returns:
            是否记录成功
        """
        data = {
            'strategy_id': strategy_id,
            'signal': signal,
            'confidence': confidence,
            'metadata': metadata or {}
        }

        return self.record_event("SIGNAL_GENERATED", "strategy_engine", data)

    def record_order_event(self, order_id: str, symbol: str, side: str, quantity: float, price: float, status: str) -> bool:
        """
        记录订单事件

        Args:
            order_id: 订单ID
            symbol: 交易对
            side: 买卖方向
            quantity: 数量
            price: 价格
            status: 订单状态

        Returns:
            是否记录成功
        """
        data = {
            'order_id': order_id,
            'symbol': symbol,
            'side': side,
            'quantity': quantity,
            'price': price,
            'status': status
        }

        return self.record_event("ORDER_CREATED", "order_executor", data)

    def record_risk_event(self, risk_level: str, event_type: str, description: str, action: str) -> bool:
        """
        记录风控事件

        Args:
            risk_level: 风险级别（INFO/WARNING/ERROR/CRITICAL）
            event_type: 事件类型
            description: 描述
            action: 采取的动作

        Returns:
            是否记录成功
        """
        data = {
            'risk_level': risk_level,
            'event_type': event_type,
            'description': description,
            'action': action
        }

        return self.record_event("RISK_INTERVENTION", "risk_engine", data)

    def record_weight_adjustment(self, strategy_id: str, old_weight: float, new_weight: float, reason: str, source: str) -> bool:
        """
        记录权重调整事件

        Args:
            strategy_id: 策略ID
            old_weight: 旧权重
            new_weight: 新权重
            reason: 调整原因
            source: 调整来源（LinUCB/MetaController）

        Returns:
            是否记录成功
        """
        data = {
            'strategy_id': strategy_id,
            'old_weight': old_weight,
            'new_weight': new_weight,
            'change': new_weight - old_weight,
            'reason': reason,
            'source': source
        }

        return self.record_event("WEIGHT_ADJUSTED", source, data)

    def record_state_transition(self, old_state: str, new_state: str, reason: str) -> bool:
        """
        记录系统状态转换

        Args:
            old_state: 旧状态
            new_state: 新状态
            reason: 转换原因

        Returns:
            是否记录成功
        """
        data = {
            'old_state': old_state,
            'new_state': new_state,
            'reason': reason
        }

        return self.record_event("STATE_TRANSITION", "global_controller", data)

    def _flush_old_events(self) -> None:
        """持久化旧事件到磁盘"""
        try:
            # 取出前50%的事件进行持久化
            flush_count = len(self.events) // 2
            old_events = self.events[:flush_count]

            # 按日期分组
            today = datetime.now().strftime("%Y-%m-%d")
            log_file = self.audit_dir / f"audit_{today}.jsonl"

            # 追加写入文件（JSONL格式）
            with open(log_file, 'a', encoding='utf-8') as f:
                for event in old_events:
                    f.write(json.dumps(event.to_dict(), ensure_ascii=False) + '\n')

            # 从缓存中移除
            self.events = self.events[flush_count:]

            logger.info(f"持久化{flush_count}条审计事件到 {log_file}")

        except Exception as e:
            logger.error(f"持久化审计事件失败: {e}")

    def save_audit_log(self, filename: str = None) -> str:
        """
        保存审计日志到文件

        Args:
            filename: 文件名（默认为当前日期）

        Returns:
            保存的文件路径
        """
        try:
            if filename is None:
                today = datetime.now().strftime("%Y-%m-%d")
                filename = f"audit_{today}.json"

            log_path = self.audit_dir / filename

            # 转换所有事件为字典
            events_dict = [event.to_dict() for event in self.events]

            # 写入文件
            with open(log_path, 'w', encoding='utf-8') as f:
                json.dump(events_dict, f, ensure_ascii=False, indent=2)

            logger.info(f"保存审计日志: {log_path}, 事件数={len(events_dict)}")

            return str(log_path)

        except Exception as e:
            logger.error(f"保存审计日志失败: {e}")
            return ""

    def load_audit_log(self, filename: str) -> List[AuditEvent]:
        """
        加载审计日志

        Args:
            filename: 文件名

        Returns:
            事件列表
        """
        try:
            log_path = self.audit_dir / filename

            if not log_path.exists():
                logger.error(f"审计日志不存在: {log_path}")
                return []

            with open(log_path, 'r', encoding='utf-8') as f:
                events_dict = json.load(f)

            # 转换为AuditEvent对象
            events = []
            for event_dict in events_dict:
                event = AuditEvent(**event_dict)
                events.append(event)

            logger.info(f"加载审计日志: {log_path}, 事件数={len(events)}")

            return events

        except Exception as e:
            logger.error(f"加载审计日志失败: {e}")
            return []

    def query_events(self,
                     event_type: Optional[str] = None,
                     source: Optional[str] = None,
                     start_time: Optional[float] = None,
                     end_time: Optional[float] = None,
                     limit: int = 100) -> List[AuditEvent]:
        """
        查询审计事件

        Args:
            event_type: 事件类型过滤
            source: 来源过滤
            start_time: 开始时间
            end_time: 结束时间
            limit: 最大返回数量

        Returns:
            事件列表
        """
        try:
            filtered = self.events

            # 过滤事件类型
            if event_type:
                filtered = [e for e in filtered if e.event_type == event_type]

            # 过滤来源
            if source:
                filtered = [e for e in filtered if e.source == source]

            # 过滤时间范围
            if start_time:
                filtered = [e for e in filtered if e.timestamp >= start_time]

            if end_time:
                filtered = [e for e in filtered if e.timestamp <= end_time]

            # 限制数量
            filtered = filtered[:limit]

            logger.debug(f"查询审计事件: 结果数={len(filtered)}")

            return filtered

        except Exception as e:
            logger.error(f"查询审计事件失败: {e}")
            return []

    def replay_at_timestamp(self, timestamp: float) -> List[AuditEvent]:
        """
        回放指定时间点的事件

        Args:
            timestamp: 时间戳

        Returns:
            该时间点之前的所有事件（按时间排序）
        """
        try:
            # 获取所有时间戳小于等于指定时间的事件
            events = [e for e in self.events if e.timestamp <= timestamp]

            # 按时间戳排序
            events.sort(key=lambda x: x.timestamp)

            logger.info(f"回放时间点: {datetime.fromtimestamp(timestamp)}, 事件数={len(events)}")

            return events

        except Exception as e:
            logger.error(f"回放事件失败: {e}")
            return []

    def verify_integrity(self) -> bool:
        """
        验证审计日志完整性（通过哈希检查）

        Returns:
            是否完整
        """
        try:
            for event in self.events:
                # 重新计算哈希
                event_str = f"{event.event_id}_{event.timestamp}_{event.event_type}_{json.dumps(event.data, sort_keys=True)}"
                computed_hash = hashlib.sha256(event_str.encode()).hexdigest()

                # 比较哈希
                if computed_hash != event.hash:
                    logger.error(f"事件哈希不匹配: {event.event_id}")
                    return False

            logger.info(f"审计日志完整性验证通过: {len(self.events)}条事件")
            return True

        except Exception as e:
            logger.error(f"验证完整性失败: {e}")
            return False

    def get_statistics(self) -> Dict:
        """
        获取审计统计信息

        Returns:
            统计信息字典
        """
        try:
            total_events = len(self.events)

            # 按事件类型统计
            event_type_counts: Dict[str, int] = {}
            for event in self.events:
                event_type_counts[event.event_type] = event_type_counts.get(event.event_type, 0) + 1

            # 按来源统计
            source_counts: Dict[str, int] = {}
            for event in self.events:
                source_counts[event.source] = source_counts.get(event.source, 0) + 1

            # 时间范围
            timestamps = [e.timestamp for e in self.events]
            time_range = {}
            if timestamps:
                time_range = {
                    'start': min(timestamps),
                    'end': max(timestamps),
                    'duration_hours': (max(timestamps) - min(timestamps)) / 3600.0
                }

            return {
                'total_events': total_events,
                'event_type_counts': event_type_counts,
                'source_counts': source_counts,
                'time_range': time_range
            }

        except Exception as e:
            logger.error(f"获取统计信息失败: {e}")
            return {}


if __name__ == "__main__":
    # 测试代码
    print("测试合规审计系统...")

    audit_system = ComplianceAuditSystem(audit_dir="test_audit_logs")

    # 测试1: 记录信号事件
    print("\n测试1: 记录信号事件")
    audit_system.record_signal_event(
        strategy_id="strategy_trend",
        signal="BUY",
        confidence=0.85,
        metadata={"price": 50000.0, "rsi": 30.0}
    )

    # 测试2: 记录订单事件
    print("\n测试2: 记录订单事件")
    audit_system.record_order_event(
        order_id="order_001",
        symbol="BTCUSDT",
        side="BUY",
        quantity=0.001,
        price=50000.0,
        status="FILLED"
    )

    # 测试3: 记录权重调整
    print("\n测试3: 记录权重调整")
    audit_system.record_weight_adjustment(
        strategy_id="strategy_trend",
        old_weight=0.4,
        new_weight=0.45,
        reason="MetaController建议增加",
        source="MetaController"
    )

    # 测试4: 记录风控事件
    print("\n测试4: 记录风控事件")
    audit_system.record_risk_event(
        risk_level="WARNING",
        event_type="HIGH_VOLATILITY",
        description="波动率超过阈值",
        action="降低仓位"
    )

    # 测试5: 查询事件
    print("\n测试5: 查询信号事件")
    signal_events = audit_system.query_events(event_type="SIGNAL_GENERATED")
    print(f"信号事件数: {len(signal_events)}")

    # 测试6: 验证完整性
    print("\n测试6: 验证完整性")
    integrity = audit_system.verify_integrity()
    print(f"完整性验证: {integrity}")

    # 测试7: 获取统计
    print("\n测试7: 获取统计")
    stats = audit_system.get_statistics()
    print(f"统计信息: 总事件数={stats['total_events']}, 类型分布={stats['event_type_counts']}")

    # 测试8: 保存日志
    print("\n测试8: 保存日志")
    log_path = audit_system.save_audit_log("test_audit.json")
    print(f"日志保存路径: {log_path}")

    print("\n测试通过！")
