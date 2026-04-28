#!/usr/bin/env python3
"""
健康度检查脚本 - v1.0.1 Stable
修复事件总线误报和日志残余检查
"""

import sys
import os
from typing import Dict, List

sys.path.insert(0, os.path.abspath('.'))

try:
    from scripts.logger_factory import get_logger
    logger = get_logger("health_check")
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("health_check")


class HealthChecker:
    """健康度检查器"""

    def __init__(self):
        self.score = 100
        self.issues: List[str] = []
        self.warnings: List[str] = []

    def check_module_loadability(self) -> bool:
        """检查模块可加载性"""
        # 使用模块路径而不是脚本路径
        modules = [
            'global_controller',
            'event_bus',
            'strategy_engine',
            'risk_engine',
            'order_lifecycle_manager',
            'market_scanner',
            'ev_filter',
            'repair_upgrade_protocol',
            'strategy_lab',
            'historical_data_loader',
            'backtest_adapter',
            'meta_controller',
            'orderbook_feeder',
            'anomaly_detector',
        ]

        failed = []
        for module_name in modules:
            try:
                # 先尝试从scripts导入
                __import__(f'scripts.{module_name}')
                logger.info(f"✓ scripts.{module_name}")
            except Exception as e1:
                try:
                    # 尝试直接导入
                    __import__(module_name)
                    logger.info(f"✓ {module_name}")
                except Exception as e2:
                    # 特殊处理risk_engine：尝试直接导入RiskEngine类
                    if module_name == 'risk_engine':
                        try:
                            from scripts.risk_engine import RiskEngine
                            logger.info(f"✓ scripts.risk_engine (class import)")
                        except Exception as e3:
                            failed.append(module_name)
                            logger.error(f"✗ {module_name}: {e1} / {e2} / {e3}")
                    else:
                        failed.append(module_name)
                        logger.error(f"✗ {module_name}: {e1} / {e2}")

        if failed:
            self.score -= len(failed) * 5
            self.issues.append(f"模块加载失败: {', '.join(failed)}")
            return False
        return True

    def check_event_bus(self) -> bool:
        """检查事件总线状态（修复误报）"""
        try:
            from event_bus import get_event_bus
            event_bus = get_event_bus()
            logger.info(f"✓ 事件总线运行中")
        except ImportError:
            try:
                from scripts.event_bus import get_event_bus
                event_bus = get_event_bus()
                logger.info(f"✓ 事件总线运行中")
            except Exception as e:
                self.score -= 10
                self.issues.append(f"事件总线检查失败: {e}")
                return False

        # v1.0.1修复: 无订阅者是正常的初始化状态
        # 仅检查事件总线实例是否存在和核心方法
        if not hasattr(event_bus, 'publish') or not hasattr(event_bus, 'subscribe'):
            self.score -= 10
            self.issues.append("事件总线核心方法缺失")
            return False

        # 检查订阅者数量（仅供参考，不扣分）
        subscribers_dict = getattr(event_bus, '_subscribers', {})
        total_subscribers = sum(len(v) if isinstance(v, (list, dict)) else 1 for v in subscribers_dict.values())
        logger.info(f"✓ 事件订阅者: {total_subscribers} 个（初始化状态）")

        return True

    def check_config_access(self) -> bool:
        """检查配置访问"""
        try:
            config_files = ['config.yaml', 'config.json']
            missing = []
            for config_file in config_files:
                if not os.path.exists(config_file):
                    missing.append(config_file)

            if missing:
                self.score -= 5
                self.warnings.append(f"配置文件缺失: {', '.join(missing)}")
                return False

            logger.info(f"✓ 配置文件存在")
            return True

        except Exception as e:
            self.score -= 5
            self.issues.append(f"配置检查失败: {e}")
            return False

    def check_residual_logs(self) -> bool:
        """检查日志残余（排除测试代码）"""
        try:
            # v1.0.1修复: 仅检查核心模块，排除测试代码
            core_modules = [
                'scripts/global_controller.py',
                'scripts/event_bus.py',
                'scripts/strategy_engine.py',
                'scripts/risk_engine.py',
                'scripts/order_lifecycle_manager.py',
                'scripts/market_scanner.py',
                'scripts/ev_filter.py',
                'scripts/repair_upgrade_protocol.py',
                'scripts/strategy_lab.py',
                'scripts/historical_data_loader.py',
                'scripts/backtest_adapter.py',
                'scripts/meta_controller.py',
                'scripts/orderbook_feeder.py',
                'scripts/anomaly_detector.py',
            ]

            count = 0
            for module in core_modules:
                if not os.path.exists(module):
                    continue

                with open(module, 'r', encoding='utf-8') as f:
                    lines = f.readlines()

                in_main_block = False
                for line in lines:
                    stripped = line.strip()

                    # 跳过注释
                    if stripped.startswith('#'):
                        continue

                    # 检测__main__块
                    if 'if __name__' in line:
                        in_main_block = True
                        continue

                    # 跳过__main__块内的print
                    if in_main_block:
                        continue

                    # 统计print（排除logger.debug等的误报）
                    if 'print(' in line:
                        # 确保是真正的print调用
                        if stripped.startswith('print(') or '(' in line[line.index('print('):]:
                            count += 1

            logger.info(f"✓ 核心模块残余print语句: {count} 个")

            if count > 0:
                self.score -= count  # 每个扣1分
                self.warnings.append(f"核心模块残余print语句: {count}个")
                return False

            return True

        except Exception as e:
            logger.warning(f"日志检查跳过: {e}")
            return True

    def check_data_directory(self) -> bool:
        """检查数据目录"""
        try:
            data_dir = "assets/data"
            if not os.path.exists(data_dir):
                self.score -= 5
                self.warnings.append(f"数据目录不存在: {data_dir}")
                return False

            logger.info(f"✓ 数据目录存在")
            return True

        except Exception as e:
            self.score -= 5
            self.issues.append(f"数据目录检查失败: {e}")
            return False

    def run_all_checks(self) -> Dict:
        """运行所有检查"""
        logger.info("=" * 50)
        logger.info("杀手锏交易系统 v1.0.1 Stable - 健康度检查")
        logger.info("=" * 50)

        checks = [
            ("模块可加载性", self.check_module_loadability),
            ("事件总线状态", self.check_event_bus),
            ("配置访问", self.check_config_access),
            ("日志残余", self.check_residual_logs),
            ("数据目录", self.check_data_directory),
        ]

        for name, check_func in checks:
            logger.info(f"\n检查: {name}")
            check_func()

        # 计算最终得分
        self.score = max(0, min(100, self.score))

        logger.info("\n" + "=" * 50)
        logger.info(f"健康得分: {self.score}/100")
        logger.info("=" * 50)

        if self.issues:
            logger.error(f"\n严重问题 ({len(self.issues)}):")
            for issue in self.issues:
                logger.error(f"  - {issue}")

        if self.warnings:
            logger.warning(f"\n警告 ({len(self.warnings)}):")
            for warning in self.warnings:
                logger.warning(f"  - {warning}")

        # 评估结果
        if self.score >= 90:
            logger.info("\n✓ 系统状态: 优秀")
        elif self.score >= 80:
            logger.info("\n⚠ 系统状态: 良好")
        elif self.score >= 70:
            logger.info("\n⚠ 系统状态: 一般")
        else:
            logger.error("\n✗ 系统状态: 需要修复")

        return {
            'score': self.score,
            'issues': self.issues,
            'warnings': self.warnings
        }


if __name__ == "__main__":
    checker = HealthChecker()
    result = checker.run_all_checks()

    # 退出码
    if result['score'] >= 80:
        sys.exit(0)
    else:
        sys.exit(1)
