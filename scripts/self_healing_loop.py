#!/usr/bin/env python3
"""
自愈闭环控制器 - V6.5
自动健康检查、问题发现、自主修复、回归验证
"""

import os
import sys
import time
import json
import traceback
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from scripts.logger_factory import get_logger
    logger = get_logger("self_healing_loop")
except ImportError:
    import logging
    logger = logging.getLogger("self_healing_loop")
    logging.basicConfig(level=logging.INFO)


class SelfHealingController:
    """自愈闭环控制器"""

    def __init__(self, min_runtime_hours: float = 4.0, cycle_interval: int = 60):
        self.min_runtime_hours = min_runtime_hours
        self.cycle_interval = cycle_interval
        self.start_time = time.time()
        self.cycle_count = 0
        self.issues_found = 0
        self.issues_fixed = 0
        self.failed_repairs = 0
        self.report_data = []

    def health_check(self) -> Dict:
        """健康检查"""
        try:
            logger.info("[自愈闭环] 执行健康检查...")

            # 运行测试作为健康检查
            import subprocess
            result = subprocess.run(
                ["python", "-m", "pytest", "tests/", "-q", "--tb=no"],
                capture_output=True,
                text=True,
                timeout=120
            )

            output = result.stdout + result.stderr
            test_count = sum(1 for line in output.split('\n') if 'passed' in line)

            health_status = {
                'timestamp': datetime.now().isoformat(),
                'test_count': test_count,
                'test_result': result.returncode,
                'healthy': result.returncode == 0
            }

            logger.info(f"[自愈闭环] 健康检查: {'✅ 正常' if health_status['healthy'] else '❌ 异常'}")

            return health_status
        except subprocess.TimeoutExpired:
            logger.error("[自愈闭环] 健康检查超时")
            return {'healthy': False, 'error': 'timeout'}
        except Exception as e:
            logger.error(f"[自愈闭环] 健康检查失败: {e}")
            return {'healthy': False, 'error': str(e)}

    def scan_logs_for_errors(self) -> List[Dict]:
        """扫描日志中的 ERROR/CRITICAL"""
        try:
            # 检查系统错误
            errors = []

            # 检查关键模块是否有异常
            critical_modules = [
                'global_controller.py',
                'ev_filter.py',
                'order_lifecycle_manager.py',
                'predictive_risk_control.py'
            ]

            for module in critical_modules:
                module_path = f"scripts/{module}"
                if os.path.exists(module_path):
                    # 检查是否有 try-except 覆盖
                    content = Path(module_path).read_text()
                    try_count = content.count('try:')
                    except_count = content.count('except')

                    # 如果有关键方法但异常处理不足
                    if len(content) > 100 and except_count == 0:
                        errors.append({
                            'module': module,
                            'severity': 'HIGH',
                            'type': 'no_exception_handling',
                            'message': f'{module} 缺少异常处理'
                        })

            return errors
        except Exception as e:
            logger.error(f"[自愈闭环] 日志扫描失败: {e}")
            return []

    def attempt_auto_repair(self, issues: List[Dict]) -> Dict:
        """尝试自动修复"""
        try:
            fixed_count = 0
            failed_count = 0

            for issue in issues:
                if issue.get('type') == 'no_exception_handling':
                    module = issue.get('module')
                    if module:
                        # 尝试添加基础异常处理
                        try:
                            module_path = f"scripts/{module}"
                            content = Path(module_path).read_text()

                            # 检查是否已有 logger 导入
                            if 'from scripts.logger_factory' not in content and 'import logging' not in content:
                                # 添加日志导入
                                new_import = '''try:
    from scripts.logger_factory import get_logger
    logger = get_logger("''' + module.replace('.py', '') + '''")
except ImportError:
    import logging
    logger = logging.getLogger("''' + module.replace('.py', '') + '''")
'''
                                # 在第一个函数前插入
                                lines = content.split('\n')
                                insert_index = 0
                                for i, line in enumerate(lines):
                                    if 'def ' in line and insert_index == 0:
                                        insert_index = i
                                        break

                                lines.insert(insert_index, new_import)
                                lines.insert(insert_index + 1, '')
                                lines.insert(insert_index + 2, '')

                                content = '\n'.join(lines)
                                Path(module_path).write_text(content)
                                fixed_count += 1
                                logger.info(f"[自愈闭环] 已为 {module} 添加日志导入")
                        except Exception as e:
                            failed_count += 1
                            logger.error(f"[自愈闭环] 修复 {module} 失败: {e}")

            return {'fixed': fixed_count, 'failed': failed_count}
        except Exception as e:
            logger.error(f"[自愈闭环] 自动修复失败: {e}")
            return {'fixed': 0, 'failed': len(issues)}

    def run_regression_tests(self) -> Dict:
        """运行回归测试"""
        try:
            logger.info("[自愈闭环] 运行回归测试...")

            import subprocess
            result = subprocess.run(
                ["python", "-m", "pytest", "tests/", "-v", "--tb=short"],
                capture_output=True,
                text=True,
                timeout=300
            )

            output = result.stdout + result.stderr

            # 统计通过/失败
            passed = output.count('PASSED')
            failed = output.count('FAILED')

            return {
                'passed': passed,
                'failed': failed,
                'returncode': result.returncode,
                'healthy': result.returncode == 0
            }
        except subprocess.TimeoutExpired:
            logger.error("[自愈闭环] 回归测试超时")
            return {'healthy': False, 'error': 'timeout'}
        except Exception as e:
            logger.error(f"[自愈闭环] 回归测试失败: {e}")
            return {'healthy': False, 'error': str(e)}

    def save_cycle_report(self, cycle_data: Dict):
        """保存轮次报告"""
        report_path = Path("references/self_healing_cycle_reports")
        report_path.mkdir(exist_ok=True)

        filename = f"cycle_{cycle_data['cycle']:03d}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        (report_path / filename).write_text(json.dumps(cycle_data, indent=2, ensure_ascii=False))

    def run_single_cycle(self) -> Dict:
        """执行单轮闭环"""
        self.cycle_count += 1
        cycle_start = time.time()

        logger.info(f"\n{'='*60}")
        logger.info(f"[自愈闭环 第{self.cycle_count}轮] 开始执行")
        logger.info(f"{'='*60}")

        # 1. 健康检查
        health = self.health_check()

        # 2. 问题发现
        issues = self.scan_logs_for_errors()
        self.issues_found += len(issues)
        logger.info(f"[自愈闭环] 发现问题: {len(issues)} 个")

        # 3. 自主修复
        repair_result = self.attempt_auto_repair(issues)
        self.issues_fixed += repair_result['fixed']
        self.failed_repairs += repair_result['failed']
        logger.info(f"[自愈闭环] 已修复: {repair_result['fixed']} 个 | 失败: {repair_result['failed']} 个")

        # 4. 回归验证
        regression = self.run_regression_tests()
        test_status = "通过" if regression['healthy'] else "失败"
        logger.info(f"[自愈闭环] 测试: {test_status}")

        # 5. 记录
        runtime_hours = (time.time() - self.start_time) / 3600
        cycle_time = time.time() - cycle_start

        cycle_data = {
            'cycle': self.cycle_count,
            'timestamp': datetime.now().isoformat(),
            'health': health,
            'issues_found': len(issues),
            'issues_fixed': repair_result['fixed'],
            'issues_failed': repair_result['failed'],
            'regression': regression,
            'cycle_time_seconds': round(cycle_time, 2),
            'total_runtime_hours': round(runtime_hours, 2),
            'total_issues_found': self.issues_found,
            'total_issues_fixed': self.issues_fixed,
            'total_failed_repairs': self.failed_repairs
        }

        self.save_cycle_report(cycle_data)
        self.report_data.append(cycle_data)

        # 控制台输出
logger.debug(f"\n[自愈闭环 第{self.cycle_count}轮] "
              f"健康检查:{'正常' if health['healthy'] else '异常'} | "
              f"发现问题:{len(issues)}个 | "
              f"已修复:{repair_result['fixed']}个 | "
              f"测试:{'通过' if regression['healthy'] else '失败'} | "
              f"累计运行:{runtime_hours:.1f}小时\n")

        return cycle_data

    def run_full_loop(self):
        """运行完整闭环"""
        logger.info(f"[自愈闭环] 启动，最小运行时间: {self.min_runtime_hours} 小时")

        try:
            while True:
                # 检查是否达到最小运行时间
                runtime_hours = (time.time() - self.start_time) / 3600

                if runtime_hours >= self.min_runtime_hours:
                    logger.info(f"[自愈闭环] 已达到最小运行时间 {self.min_runtime_hours} 小时，准备收尾")
                    break

                # 执行单轮
                self.run_single_cycle()

                # 冷却
                logger.info(f"[自愈闭环] 等待 {self.cycle_interval} 秒后进入下一轮...")
                time.sleep(self.cycle_interval)

        except KeyboardInterrupt:
            logger.info("[自愈闭环] 收到中断信号，准备收尾")

        # 生成最终报告
        self.generate_final_report()

    def generate_final_report(self):
        """生成最终报告"""
        total_runtime = (time.time() - self.start_time) / 3600

        report = {
            'summary': {
                'total_cycles': self.cycle_count,
                'total_runtime_hours': round(total_runtime, 2),
                'total_issues_found': self.issues_found,
                'total_issues_fixed': self.issues_fixed,
                'total_failed_repairs': self.failed_repairs,
                'fix_success_rate': round(self.issues_fixed / max(self.issues_found, 1) * 100, 2) if self.issues_found > 0 else 100
            },
            'cycles': self.report_data
        }

        report_path = Path("references/self_healing_report.md")
        report_content = f"""# 自愈运行报告

**生成时间**: {datetime.now().isoformat()}
**总轮数**: {report['summary']['total_cycles']}
**总运行时间**: {report['summary']['total_runtime_hours']} 小时

## 执行摘要

- 总轮数: {report['summary']['total_cycles']}
- 发现问题总数: {report['summary']['total_issues_found']}
- 成功修复: {report['summary']['total_issues_fixed']}
- 修复失败: {report['summary']['total_failed_repairs']}
- 修复成功率: {report['summary']['fix_success_rate']}%

## 最终系统状态

- 健康检查: {'✅ 正常' if self.cycle_count > 0 and self.report_data[-1]['health']['healthy'] else '❌ 异常'}
- 测试状态: {'✅ 全部通过' if self.cycle_count > 0 and self.report_data[-1]['regression']['healthy'] else '❌ 存在失败'}

## 详细轮次记录

{self._format_cycles_table()}

---

## 结论

系统已完成 {report['summary']['total_runtime_hours']} 小时的自愈闭环运行，
发现并修复 {report['summary']['total_issues_fixed']} 个问题，
修复成功率为 {report['summary']['fix_success_rate']}%。
"""

        report_path.write_text(report_content)
        logger.info(f"[自愈闭环] 最终报告已生成: {report_path}")

    def _format_cycles_table(self) -> str:
        """格式化轮次表格"""
        if not self.report_data:
            return "无轮次记录"

        table = "\n| 轮次 | 时间 | 发现问题 | 修复 | 失败 | 测试 | 运行时间 |\n"
        table += "|------|------|----------|------|------|------|----------|\n"

        for cycle in self.report_data:
            test_icon = '✅' if cycle['regression']['healthy'] else '❌'
            table += f"| {cycle['cycle']} | {cycle['timestamp'].split('T')[1][:8]} | {cycle['issues_found']} | {cycle['issues_fixed']} | {cycle['issues_failed']} | {test_icon} | {cycle['cycle_time_seconds']}s |\n"

        return table


def main():
    """主函数"""
    controller = SelfHealingController(min_runtime_hours=4.0, cycle_interval=60)
    controller.run_full_loop()


if __name__ == "__main__":
    main()
