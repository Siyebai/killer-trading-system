#!/usr/bin/env python3
"""
修复升级协议 — 杀手锏交易系统 v1.0.3
解决修复死循环: WebSocket reconnect无限调用消耗资源且可能触发频率限制

核心设计:
1. RepairLevel — 4级修复升级(轻量→中度→软熔断→硬熔断)
2. RepairUpgradeProtocol — 修复后必验证 + 逐步升级 + 冷却等待
3. 修复轨迹持久化 + 结构化审计日志
"""

import argparse
import json
import sys
import time
import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    from scripts.logger_factory import get_logger
    logger = get_logger("repair_upgrade")
except ImportError:
    import logging
    logger = logging.getLogger("repair_upgrade")

# 导入事件总线（Phase 5.6新增）
try:
    from scripts.event_bus import get_event_bus
    EVENT_BUS_AVAILABLE = True
except ImportError:
    EVENT_BUS_AVAILABLE = False


# ============================================================
# 1. 修复等级定义
# ============================================================

class RepairLevel(Enum):
    """修复升级等级"""
    L1_LIGHT = "L1_LIGHT"               # 轻量级: 单策略修复(如ws_reconnect)
    L2_MEDIUM = "L2_MEDIUM"             # 中度级: 组合修复(如listenkey_renew + ws_reconnect)
    L3_SOFT_BREAKER = "L3_SOFT_BREAKER" # 软熔断: 暂停依赖该通道的功能
    L4_HARD_BREAKER = "L4_HARD_BREAKER" # 硬熔断: 等待人工介入


# 各等级冷却等待时间(秒)
LEVEL_COOLDOWN = {
    RepairLevel.L1_LIGHT: 5,
    RepairLevel.L2_MEDIUM: 30,
    RepairLevel.L3_SOFT_BREAKER: 300,
    RepairLevel.L4_HARD_BREAKER: 0,  # 硬熔断需人工介入,无自动冷却
}

# 各等级最大尝试次数
LEVEL_MAX_ATTEMPTS = {
    RepairLevel.L1_LIGHT: 3,
    RepairLevel.L2_MEDIUM: 2,
    RepairLevel.L3_SOFT_BREAKER: 1,
    RepairLevel.L4_HARD_BREAKER: 0,  # 不自动尝试
}


# ============================================================
# 2. 修复记录
# ============================================================

@dataclass
class RepairRecord:
    """单次修复记录"""
    module: str
    level: RepairLevel
    strategy: str
    success: bool
    verified: bool = False
    timestamp: float = 0.0
    duration_ms: float = 0.0
    error: str = ""
    pre_snapshot: Dict = field(default_factory=dict)
    post_snapshot: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "module": self.module,
            "level": self.level.value,
            "strategy": self.strategy,
            "success": self.success,
            "verified": self.verified,
            "timestamp": self.timestamp,
            "duration_ms": round(self.duration_ms, 2),
            "error": self.error,
        }


# ============================================================
# 3. 修复升级协议
# ============================================================

class RepairUpgradeProtocol:
    """
    修复升级协议

    核心逻辑:
    1. 每次修复前拍快照(用于回滚)
    2. 按等级逐步升级(L1→L2→L3→L4)
    3. 每级有最大尝试次数和冷却时间
    4. 修复后必须验证(N秒后重新检查)
    5. 验证失败则升级到下一级
    6. 所有操作写入审计日志

    升级流程:
    L1: ws_reconnect (尝试3次,间隔5s)
    L2: listenkey_renew + ws_reconnect (尝试2次,间隔30s)
    L3: 触发SOFT_BREAKER,暂停该通道 (1次,间隔300s)
    L4: 触发HARD_BREAKER,等待人工介入
    """

    def __init__(self, verify_wait_seconds: float = 10.0):
        self.verify_wait_seconds = verify_wait_seconds
        self.records: List[RepairRecord] = []
        self._module_levels: Dict[str, RepairLevel] = {}  # 每个模块当前升级等级
        self._module_attempts: Dict[str, int] = {}         # 当前等级已尝试次数
        self._repair_strategies: Dict[str, Dict[RepairLevel, Callable]] = {}
        self._verify_funcs: Dict[str, Callable] = {}
        self._state_change_callback: Optional[Callable] = None

    def register_strategies(self, module: str,
                           strategies: Dict[RepairLevel, Callable],
                           verify_func: Optional[Callable] = None):
        """
        注册模块的分级修复策略。

        Args:
            module: 模块名称
            strategies: {RepairLevel: repair_func} 修复策略映射
            verify_func: 修复后验证函数
        """
        self._repair_strategies[module] = strategies
        self._verify_funcs[module] = verify_func or (lambda: True)
        self._module_levels.setdefault(module, RepairLevel.L1_LIGHT)
        self._module_attempts.setdefault(module, 0)

    def set_state_change_callback(self, callback: Callable):
        """设置状态变更回调(用于触发GlobalState转换)"""
        self._state_change_callback = callback

    async def attempt_repair(self, module: str) -> RepairRecord:
        """
        尝试修复模块(遵循升级协议)。

        Args:
            module: 不健康的模块名称

        Returns:
            RepairRecord
        """
        current_level = self._module_levels.get(module, RepairLevel.L1_LIGHT)
        attempts = self._module_attempts.get(module, 0)
        max_attempts = LEVEL_MAX_ATTEMPTS.get(current_level, 1)

        # 检查是否需要升级
        if attempts >= max_attempts and current_level != RepairLevel.L4_HARD_BREAKER:
            next_level = self._next_level(current_level)
            logger.warning("Repair level upgrade", extra={"extra_data": {
                "module": module,
                "from": current_level.value,
                "to": next_level.value,
            }})
            self._module_levels[module] = next_level
            self._module_attempts[module] = 0
            current_level = next_level
            attempts = 0

        # 硬熔断级不自动尝试
        if current_level == RepairLevel.L4_HARD_BREAKER:
            record = RepairRecord(
                module=module, level=current_level, strategy="manual_intervention",
                success=False, timestamp=time.time(),
                error="HARD_BREAKER: requires manual intervention"
            )
            self.records.append(record)
            logger.critical("Manual intervention required", extra={"extra_data": {
                "module": module
            }})
            return record

        # 获取修复策略
        strategies = self._repair_strategies.get(module, {})
        repair_func = strategies.get(current_level)

        if not repair_func:
            record = RepairRecord(
                module=module, level=current_level, strategy="none",
                success=False, timestamp=time.time(),
                error=f"No repair strategy for level {current_level.value}"
            )
            self.records.append(record)
            return record

        # 冷却等待
        cooldown = LEVEL_COOLDOWN.get(current_level, 5)
        if attempts > 0:
            logger.info("Repair cooldown", extra={"extra_data": {
                "module": module, "cooldown_s": cooldown
            }})
            await asyncio.sleep(cooldown)

        # 执行修复
        start = time.time()
        try:
            success = await repair_func() if asyncio.iscoroutinefunction(repair_func) else repair_func()
        except Exception as e:
            success = False
            error = str(e)

        duration = (time.time() - start) * 1000

        # 修复后验证
        verified = False
        if success:
            logger.info("Repair executed, verifying...", extra={"extra_data": {
                "module": module, "level": current_level.value
            }})
            # 等待N秒后验证
            await asyncio.sleep(self.verify_wait_seconds)
            try:
                verify_func = self._verify_funcs.get(module, lambda: True)
                verified = await verify_func() if asyncio.iscoroutinefunction(verify_func) else verify_func()
            except Exception as e:
                verified = False
                logger.error("Repair verification failed", extra={"extra_data": {
                    "module": module, "error": str(e)
                }})

            if verified:
                # 验证成功,重置升级等级
                self._module_levels[module] = RepairLevel.L1_LIGHT
                self._module_attempts[module] = 0
                logger.info("Repair verified and reset", extra={"extra_data": {
                    "module": module
                }})
            else:
                # 验证失败,标记success为False
                success = False
                logger.warning("Repair verification failed, will escalate", extra={"extra_data": {
                    "module": module
                }})

        self._module_attempts[module] = self._module_attempts.get(module, 0) + 1

        record = RepairRecord(
            module=module, level=current_level,
            strategy=repair_func.__name__ if hasattr(repair_func, '__name__') else str(current_level),
            success=success, verified=verified,
            timestamp=time.time(), duration_ms=duration,
            error="" if success else (error if 'error' in dir() else "verification_failed" if not verified else "repair_failed")
        )
        self.records.append(record)

        # 状态变更回调(L3/L4级)
        if self._state_change_callback and not success:
            if current_level == RepairLevel.L3_SOFT_BREAKER:
                await self._state_change_callback(module, "SOFT_BREAKER",
                    f"Repair L3 triggered for {module}")
            elif current_level == RepairLevel.L4_HARD_BREAKER:
                await self._state_change_callback(module, "HARD_BREAKER",
                    f"Repair L4 triggered for {module}")

        # 审计日志
        logger.info("Repair attempt completed", extra={"extra_data": record.to_dict()})

        # 广播repair.action_taken事件（Phase 5.6新增）
        if EVENT_BUS_AVAILABLE:
            self._publish_repair_event(record, module, current_level)

        return record

    def _publish_repair_event(self, record: RepairRecord, module: str, level: RepairLevel):
        """
        广播修复事件（Phase 5.6新增）

        Args:
            record: 修复记录
            module: 模块名称
            level: 修复等级
        """
        try:
            event_bus = get_event_bus()
            event_bus.publish(
                "repair.attempted",
                {
                    "module": module,
                    "level": level.value,
                    "strategy": record.strategy,
                    "success": record.success,
                    "verified": record.verified,
                    "duration_ms": record.duration_ms,
                    "attempts": self._module_attempts.get(module, 0),
                    "max_attempts": LEVEL_MAX_ATTEMPTS.get(level, 1),
                    "will_escalate": not record.success and level != RepairLevel.L4_HARD_BREAKER
                },
                source="repair_upgrade_protocol"
            )
            logger.debug(f"修复事件已广播: {module} L{level.value} - {'成功' if record.success else '失败'}")
        except Exception as e:
            logger.error(f"修复事件广播失败: {e}")

    @staticmethod
    def _next_level(current: RepairLevel) -> RepairLevel:
        """获取下一升级等级"""
        order = [
            RepairLevel.L1_LIGHT,
            RepairLevel.L2_MEDIUM,
            RepairLevel.L3_SOFT_BREAKER,
            RepairLevel.L4_HARD_BREAKER,
        ]
        idx = order.index(current)
        return order[min(idx + 1, len(order) - 1)]

    def get_module_status(self, module: str) -> Dict:
        """获取模块修复状态"""
        return {
            "module": module,
            "current_level": self._module_levels.get(module, RepairLevel.L1_LIGHT).value,
            "attempts_at_level": self._module_attempts.get(module, 0),
        }

    def get_audit_trail(self, module: Optional[str] = None) -> List[Dict]:
        """获取修复审计轨迹"""
        records = self.records
        if module:
            records = [r for r in records if r.module == module]
        return [r.to_dict() for r in records[-50:]]  # 最近50条

    def get_stats(self) -> Dict:
        """获取修复统计"""
        total = len(self.records)
        success = sum(1 for r in self.records if r.success)
        verified = sum(1 for r in self.records if r.verified)
        return {
            "total_repairs": total,
            "successful": success,
            "verified": verified,
            "success_rate": round(success / total, 3) if total > 0 else 0,
            "verification_rate": round(verified / max(success, 1), 3),
            "modules_status": {
                m: self.get_module_status(m) for m in self._repair_strategies
            }
        }


# ============================================================
# 命令行接口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="修复升级协议验证")
    parser.add_argument("--stats", action="store_true", help="输出修复统计")
    parser.add_argument("--audit", type=str, default=None, help="输出指定模块的审计轨迹")
    parser.add_argument("--simulate", action="store_true", help="模拟修复升级流程")
    args = parser.parse_args()

    protocol = RepairUpgradeProtocol(verify_wait_seconds=0.1)

    if args.simulate:
        # 模拟WebSocket断连的完整升级流程
        attempt_count = {"count": 0}

        async def ws_reconnect():
            attempt_count["count"] += 1
            return attempt_count["count"] > 5  # 前5次失败,第6次成功

        async def combined_repair():
            attempt_count["count"] += 1
            return attempt_count["count"] > 8

        async def verify():
            return attempt_count["count"] > 6

        protocol.register_strategies(
            "websocket_public",
            {
                RepairLevel.L1_LIGHT: ws_reconnect,
                RepairLevel.L2_MEDIUM: combined_repair,
                RepairLevel.L3_SOFT_BREAKER: lambda: False,
            },
            verify_func=verify
        )

        async def run_sim():
            results = []
            for i in range(12):
                record = await protocol.attempt_repair("websocket_public")
                results.append(record.to_dict())
                if record.success and record.verified:
                    break
            return results
        results = asyncio.run(run_sim())
        logger.info(json.dumps({"simulation": results, "stats": protocol.get_stats()},
                                ensure_ascii=False, indent=2, default=str))
        return

    if args.stats:
        logger.info(json.dumps(protocol.get_stats(), ensure_ascii=False, indent=2))
        return

    if args.audit:
        logger.info(json.dumps(protocol.get_audit_trail(args.audit), ensure_ascii=False, indent=2))
        return

    logger.info(json.dumps({"status": "ok", "message": "Use --stats, --audit <module>, or --simulate"},
                            ensure_ascii=False))


if __name__ == "__main__":
    main()
