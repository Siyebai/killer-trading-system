#!/usr/bin/env python3
"""
EDF扫描调度器 — 杀手锏交易系统 v1.0.2
解决多品种并行调度黑盒: 高频品种与低频品种争抢同一时间片资源

核心设计:
1. 最早截止时间优先(EDF)调度 — 高频品种天然拥有更早截止时间,动态获得更高优先级
2. 延迟感知降频 — 品种决策延迟>200ms时自动降频,释放资源
3. 优先级动态调整 — 根据品种的交易活跃度和收益贡献动态调整
"""

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    from scripts.logger_factory import get_logger
    logger = get_logger("edf_scheduler")
except ImportError:
    import logging
    logger = logging.getLogger("edf_scheduler")


# ============================================================
# 1. 品种调度状态
# ============================================================

class SchedulePriority(Enum):
    HIGH = "HIGH"           # 高频品种(1m/5m K线)
    MEDIUM = "MEDIUM"       # 中频品种(15m K线)
    LOW = "LOW"             # 低频品种(1h/4h K线)
    DEMOTED = "DEMOTED"     # 降频品种(延迟过高)


# 时间帧 → 截止时间映射(秒)
TIMEFRAME_DEADLINE = {
    "1m": 60,      # 1分钟K线, 截止60秒
    "5m": 300,     # 5分钟K线, 截止300秒
    "15m": 900,    # 15分钟K线, 截止900秒
    "1h": 3600,    # 1小时K线, 截止3600秒
    "4h": 14400,   # 4小时K线, 截止14400秒
}

# 时间帧 → 默认优先级
TIMEFRAME_PRIORITY = {
    "1m": SchedulePriority.HIGH,
    "5m": SchedulePriority.HIGH,
    "15m": SchedulePriority.MEDIUM,
    "1h": SchedulePriority.LOW,
    "4h": SchedulePriority.LOW,
}


# ============================================================
# 2. 品种调度条目
# ============================================================

@dataclass
class SymbolSchedule:
    """品种调度条目"""
    symbol: str
    timeframe: str
    priority: SchedulePriority = SchedulePriority.MEDIUM
    deadline_seconds: float = 300.0
    last_scan_time: float = 0.0
    last_scan_duration_ms: float = 0.0
    scan_count: int = 0
    error_count: int = 0
    consecutive_slow: int = 0        # 连续慢扫描次数
    is_demoted: bool = False         # 是否被降频
    demoted_until: float = 0.0       # 降频截止时间

    @property
    def urgency(self) -> float:
        """
        紧迫度(0.0-1.0): 越接近截止时间越紧迫
        """
        elapsed = time.time() - self.last_scan_time
        ratio = elapsed / self.deadline_seconds if self.deadline_seconds > 0 else 1.0
        return min(ratio, 1.0)

    @property
    def effective_priority(self) -> SchedulePriority:
        """有效优先级(降频时为DEMOTED)"""
        if self.is_demoted and time.time() < self.demoted_until:
            return SchedulePriority.DEMOTED
        return self.priority


# ============================================================
# 3. EDF调度器
# ============================================================

class EDFScheduler:
    """
    最早截止时间优先(EDF)扫描调度器

    核心逻辑:
    1. 每个品种有基于时间帧的截止时间
    2. 调度时按紧迫度排序,最紧迫的优先执行
    3. 扫描延迟>200ms的品种自动降频
    4. 降频品种释放资源给高紧迫度品种
    5. 降频品种在冷却期后自动恢复

    调度策略:
    - 正常模式: 按紧迫度排序,依次执行
    - 降频模式: 跳过降频品种,仅执行高紧迫度品种
    - 恢复模式: 降频品种冷却期后恢复
    """

    def __init__(self, slow_threshold_ms: float = 200.0,
                 demote_duration_s: float = 300.0,
                 max_consecutive_slow: int = 3):
        self.slow_threshold_ms = slow_threshold_ms
        self.demote_duration_s = demote_duration_s
        self.max_consecutive_slow = max_consecutive_slow
        self.schedules: Dict[str, SymbolSchedule] = {}
        self._scan_history: List[Dict] = []

    def register_symbol(self, symbol: str, timeframe: str,
                        custom_deadline: Optional[float] = None) -> None:
        """
        注册品种到调度器。

        Args:
            symbol: 交易品种(如BTCUSDT)
            timeframe: K线时间帧(如5m/15m/1h)
            custom_deadline: 自定义截止时间(秒)
        """
        key = f"{symbol}_{timeframe}"
        priority = TIMEFRAME_PRIORITY.get(timeframe, SchedulePriority.MEDIUM)
        deadline = custom_deadline or TIMEFRAME_DEADLINE.get(timeframe, 300)

        self.schedules[key] = SymbolSchedule(
            symbol=symbol,
            timeframe=timeframe,
            priority=priority,
            deadline_seconds=deadline,
            last_scan_time=time.time() - deadline * 0.8,  # 初始接近截止
        )
        logger.info("Symbol registered", extra={"extra_data": {
            "symbol": symbol, "timeframe": timeframe,
            "priority": priority.value, "deadline": deadline
        }})

    def get_scan_order(self) -> List[str]:
        """
        获取当前扫描顺序(按紧迫度降序)。

        Returns:
            排序后的调度键列表
        """
        now = time.time()

        # 恢复已过冷却期的降频品种
        for key, sched in self.schedules.items():
            if sched.is_demoted and now >= sched.demoted_until:
                sched.is_demoted = False
                sched.consecutive_slow = 0
                logger.info("Symbol demotion expired", extra={"extra_data": {"key": key}})

        # 按有效优先级+紧迫度排序
        priority_weight = {
            SchedulePriority.HIGH: 3,
            SchedulePriority.MEDIUM: 2,
            SchedulePriority.LOW: 1,
            SchedulePriority.DEMOTED: 0,
        }

        def sort_key(key: str) -> Tuple[int, float]:
            sched = self.schedules[key]
            return (priority_weight.get(sched.effective_priority, 0), sched.urgency)

        sorted_keys = sorted(self.schedules.keys(), key=sort_key, reverse=True)
        return sorted_keys

    def record_scan(self, key: str, duration_ms: float, success: bool = True) -> Dict:
        """
        记录扫描结果并更新调度状态。

        Args:
            key: 品种键(如BTCUSDT_5m)
            duration_ms: 扫描耗时(毫秒)
            success: 是否成功

        Returns:
            调度状态变更信息
        """
        if key not in self.schedules:
            return {"error": f"Unknown key: {key}"}

        sched = self.schedules[key]
        sched.last_scan_time = time.time()
        sched.last_scan_duration_ms = duration_ms
        sched.scan_count += 1

        state_changed = False
        message = ""

        if not success:
            sched.error_count += 1
        elif duration_ms > self.slow_threshold_ms:
            sched.consecutive_slow += 1
            if sched.consecutive_slow >= self.max_consecutive_slow:
                # 降频
                sched.is_demoted = True
                sched.demoted_until = time.time() + self.demote_duration_s
                state_changed = True
                message = f"{key} demoted for {self.demote_duration_s}s (slow: {duration_ms:.0f}ms)"
                logger.warning("Symbol demoted due to slow scan", extra={"extra_data": {
                    "key": key, "duration_ms": duration_ms,
                    "threshold_ms": self.slow_threshold_ms
                }})
        else:
            sched.consecutive_slow = 0

        record = {
            "key": key,
            "duration_ms": round(duration_ms, 1),
            "success": success,
            "state_changed": state_changed,
            "message": message,
            "urgency_after": round(sched.urgency, 3),
        }
        self._scan_history.append(record)

        return record

    def get_next_symbol(self) -> Optional[Tuple[str, str]]:
        """
        获取下一个应扫描的品种。

        Returns:
            (symbol, timeframe) 或 None
        """
        order = self.get_scan_order()
        if not order:
            return None

        key = order[0]
        sched = self.schedules[key]
        return (sched.symbol, sched.timeframe)

    def get_dashboard(self) -> Dict:
        """获取调度仪表板"""
        order = self.get_scan_order()
        now = time.time()

        return {
            "total_symbols": len(self.schedules),
            "scan_order": order[:20],
            "next_symbol": self.get_next_symbol(),
            "demoted_symbols": [
                k for k, s in self.schedules.items() if s.is_demoted and now < s.demoted_until
            ],
            "symbols": {
                k: {
                    "symbol": s.symbol,
                    "timeframe": s.timeframe,
                    "priority": s.effective_priority.value,
                    "urgency": round(s.urgency, 3),
                    "last_scan_ms": round(s.last_scan_duration_ms, 1),
                    "scan_count": s.scan_count,
                    "is_demoted": s.is_demoted,
                    "consecutive_slow": s.consecutive_slow,
                }
                for k, s in self.schedules.items()
            }
        }

    def get_stats(self) -> Dict:
        """获取调度统计"""
        total_scans = sum(s.scan_count for s in self.schedules.values())
        avg_duration = (
            sum(s.last_scan_duration_ms for s in self.schedules.values())
            / max(len(self.schedules), 1)
        )
        demoted = sum(1 for s in self.schedules.values() if s.is_demoted)

        return {
            "total_symbols": len(self.schedules),
            "total_scans": total_scans,
            "avg_duration_ms": round(avg_duration, 1),
            "demoted_count": demoted,
            "slow_threshold_ms": self.slow_threshold_ms,
        }


# ============================================================
# 命令行接口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="EDF扫描调度器")
    parser.add_argument("--register", type=str, nargs=2, metavar=("SYMBOL", "TIMEFRAME"),
                       help="注册品种")
    parser.add_argument("--order", action="store_true", help="获取扫描顺序")
    parser.add_argument("--next", action="store_true", help="获取下一个品种")
    parser.add_argument("--record-scan", type=str, metavar="KEY",
                       help="记录扫描结果")
    parser.add_argument("--duration", type=float, default=100.0, help="扫描耗时(ms)")
    parser.add_argument("--success", type=bool, default=True, help="是否成功")
    parser.add_argument("--dashboard", action="store_true", help="输出仪表板")
    parser.add_argument("--demo", action="store_true", help="演示EDF调度")
    args = parser.parse_args()

    scheduler = EDFScheduler()

    if args.demo:
        # 演示: 注册多品种并展示调度顺序
        symbols = [
            ("BTCUSDT", "1m"), ("ETHUSDT", "1m"),
            ("BTCUSDT", "5m"), ("ETHUSDT", "5m"),
            ("SOLUSDT", "15m"), ("BNBUSDT", "1h"),
            ("XRPUSDT", "4h"), ("DOGEUSDT", "15m"),
        ]
        for sym, tf in symbols:
            scheduler.register_symbol(sym, tf)

        # 模拟一次扫描
        order = scheduler.get_scan_order()
        for key in order[:3]:
            scheduler.record_scan(key, duration_ms=50 + hash(key) % 200)

        # 模拟慢扫描导致降频
        for _ in range(3):
            scheduler.record_scan("BTCUSDT_1m", duration_ms=350, success=True)

        logger.info((json.dumps({)
            "scan_order": scheduler.get_scan_order(),
            "dashboard": scheduler.get_dashboard(),
            "stats": scheduler.get_stats(),
        }, ensure_ascii=False, indent=2))
        return

    if args.register:
        sym, tf = args.register
        scheduler.register_symbol(sym, tf)
        logger.info(json.dumps({"status": "registered", "symbol": sym, "timeframe": tf}))

    if args.order:
        logger.info(json.dumps(scheduler.get_scan_order(), ensure_ascii=False))

    if args.next:
        result = scheduler.get_next_symbol()
        logger.info(json.dumps({"next": result}, ensure_ascii=False))

    if args.record_scan:
        r = scheduler.record_scan(args.record_scan, args.duration, args.success)
        logger.info(json.dumps(r, ensure_ascii=False))

    if args.dashboard:
        logger.info(json.dumps(scheduler.get_dashboard(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
