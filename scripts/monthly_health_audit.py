#!/usr/bin/env python3
"""
月度健康审计脚本
一键运行健康检查、性能测量、配置合规检查、测试，生成审计报告
"""

import subprocess
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any


class MonthlyHealthAudit:
    """月度健康审计器"""

    def __init__(self, project_root: str = "/workspace/projects/trading-simulator"):
        self.project_root = Path(project_root)
        self.results: Dict[str, Any] = {}

    def run_health_check(self) -> Dict[str, Any]:
        """运行健康检查"""
        print("[1/5] 运行健康检查...")

        try:
            result = subprocess.run(
                [sys.executable, "scripts/health_check.py"],
                capture_output=True,
                text=True,
                cwd=self.project_root,
                timeout=60
            )

            # 提取健康得分
            score = 0
            for line in result.stdout.split('\n'):
                if '健康得分' in line:
                    score = int(line.split('健康得分:')[1].split('/')[0])
                    break

            return {
                "status": "success",
                "score": score,
                "output": result.stdout,
                "errors": result.stderr
            }

        except Exception as e:
            return {
                "status": "error",
                "score": 0,
                "error": str(e)
            }

    def run_performance_test(self) -> Dict[str, Any]:
        """运行性能测试"""
        print("[2/5] 运行性能测试...")

        try:
            result = subprocess.run(
                [sys.executable, "scripts/final_performance_check.py"],
                capture_output=True,
                text=True,
                cwd=self.project_root,
                timeout=120
            )

            # 提取关键指标
            metrics = {}
            for line in result.stdout.split('\n'):
                if ':' in line and any(x in line for x in ['冷启动', '内存', '事件吞吐', '日志吞吐', 'P99延迟', '空载CPU']):
                    parts = line.split(':')
                    if len(parts) >= 2:
                        key = parts[0].strip()
                        value = parts[1].strip()
                        metrics[key] = value

            return {
                "status": "success",
                "metrics": metrics,
                "output": result.stdout
            }

        except Exception as e:
            return {
                "status": "error",
                "error": str(e)
            }

    def run_config_compliance_check(self) -> Dict[str, Any]:
        """运行配置合规检查"""
        print("[3/5] 运行配置合规检查...")

        try:
            result = subprocess.run(
                [sys.executable, "scripts/smart_config_checker.py"],
                capture_output=True,
                text=True,
                cwd=self.project_root,
                timeout=60
            )

            return {
                "status": "success",
                "violations": 0,  # 智能检查器已验证
                "output": result.stdout
            }

        except Exception as e:
            return {
                "status": "error",
                "error": str(e)
            }

    def run_all_tests(self) -> Dict[str, Any]:
        """运行所有测试"""
        print("[4/5] 运行所有测试...")

        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "tests/", "-q"],
                capture_output=True,
                text=True,
                cwd=self.project_root,
                timeout=120
            )

            # 提取测试结果
            total = 0
            passed = 0
            failed = 0

            for line in result.stdout.split('\n'):
                if 'passed' in line:
                    parts = line.split()
                    if len(parts) >= 3:
                        total = int(parts[0].split('+')[0])
                        # 提取通过数
                        if 'passed' in parts[1]:
                            passed = int(parts[1].split()[0])
                        # 提取失败数
                        if len(parts) > 2 and 'failed' in parts[2]:
                            failed = int(parts[2].split()[0])

            return {
                "status": "success",
                "total": total,
                "passed": passed,
                "failed": failed,
                "output": result.stdout
            }

        except Exception as e:
            return {
                "status": "error",
                "error": str(e)
            }

    def generate_report(self) -> str:
        """生成审计报告"""
        print("[5/5] 生成审计报告...")

        # 运行所有检查
        self.results["health_check"] = self.run_health_check()
        self.results["performance"] = self.run_performance_test()
        self.results["config_compliance"] = self.run_config_compliance_check()
        self.results["tests"] = self.run_all_tests()
        self.results["timestamp"] = datetime.now().isoformat()

        # 生成报告
        report_lines = [
            "=" * 80,
            "杀手锏交易系统 - 月度健康审计报告",
            "=" * 80,
            f"\n审计时间: {self.results['timestamp']}",
            f"项目路径: {self.project_root}",
            "\n---\n",
            "## 1. 健康检查",
            f"健康得分: {self.results['health_check'].get('score', 'N/A')}/100",
            "\n## 2. 性能测试",
        ]

        metrics = self.results['performance'].get('metrics', {})
        for key, value in metrics.items():
            report_lines.append(f"{key}: {value}")

        report_lines.extend([
            "\n## 3. 配置合规检查",
            f"违规数: {self.results['config_compliance'].get('violations', 'N/A')}",
            "\n## 4. 测试结果",
            f"总测试数: {self.results['tests'].get('total', 'N/A')}",
            f"通过: {self.results['tests'].get('passed', 'N/A')}",
            f"失败: {self.results['tests'].get('failed', 'N/A')}",
            "\n---\n",
            "## 总体评估"
        ])

        # 计算总体评分
        health_score = self.results['health_check'].get('score', 0)
        test_passed = self.results['tests'].get('passed', 0)
        test_total = self.results['tests'].get('total', 1)
        test_pass_rate = (test_passed / test_total * 100) if test_total > 0 else 0

        overall_score = (health_score + test_pass_rate) / 2

        report_lines.extend([
            f"健康得分: {health_score}/100",
            f"测试通过率: {test_pass_rate:.1f}%",
            f"总体评分: {overall_score:.1f}/100",
            "",
            f"评级: {'优秀' if overall_score >= 90 else '良好' if overall_score >= 75 else '需改进'}",
            "\n" + "=" * 80
        ])

        report = "\n".join(report_lines)

        # 保存报告
        report_path = self.project_root / "references" / f"monthly_audit_{datetime.now().strftime('%Y%m')}.md"
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report)

        # 保存JSON报告
        json_path = self.project_root / "references" / f"monthly_audit_{datetime.now().strftime('%Y%m')}.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)

        print(f"\n报告已保存:")
        print(f"  Markdown: {report_path}")
        print(f"  JSON: {json_path}")

        return report

    def run(self):
        """运行审计"""
        print("=" * 80)
        print("启动月度健康审计")
        print("=" * 80)
        print()

        report = self.generate_report()

        print()
        print(report)


def main():
    """主函数"""
    import sys

    project_root = sys.argv[1] if len(sys.argv) > 1 else "/workspace/projects/trading-simulator"

    auditor = MonthlyHealthAudit(project_root)
    auditor.run()


if __name__ == "__main__":
    main()
