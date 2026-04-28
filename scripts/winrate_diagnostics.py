#!/usr/bin/env python3
"""
杀手锏交易系统 v1.0.2 - 胜率诊断系统
全面诊断系统，识别胜率低的根本原因
"""
import sys
import os
import json
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from collections import defaultdict, Counter
import logging
import warnings
warnings.filterwarnings('ignore')

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class WinRateDiagnostics:
    """胜率诊断系统"""

    def __init__(self):
        self.project_root = Path("/workspace/projects/trading-simulator")
        self.logger = logging.getLogger("winrate_diagnostics")
        self.results = {
            "timestamp": datetime.now().isoformat(),
            "version": "v1.0.2",
            "diagnostics": {}
        }

    def diagnose_all(self):
        """执行所有诊断"""
        print("=" * 70)
        print("🔍 杀手锏交易系统 v1.0.2 - 全面胜率诊断")
        print("=" * 70)

        # 诊断1：检查历史回测结果
        print("\n📊 诊断1：历史回测结果分析")
        self.diagnose_backtest_results()

        # 诊断2：检查策略信号质量
        print("\n📊 诊断2：策略信号质量分析")
        self.diagnose_signal_quality()

        # 诊断3：检查出场机制
        print("\n📊 诊断3：出场机制效果分析")
        self.diagnose_exit_mechanism()

        # 诊断4：检查市场环境识别
        print("\n📊 诊断4：市场环境识别准确性")
        self.diagnose_market_regime()

        # 诊断5：检查策略权重
        print("\n📊 诊断5：策略权重分配分析")
        self.diagnose_strategy_weights()

        # 诊断6：检查风控影响
        print("\n📊 诊断6：风控规则影响分析")
        self.diagnose_risk_control()

        # 诊断7：检查配置参数
        print("\n📊 诊断7：配置参数合理性分析")
        self.diagnose_configuration()

        # 诊断8：生成综合报告
        print("\n📊 诊断8：生成综合报告")
        self.generate_summary_report()

        # 保存诊断结果
        self.save_results()

        print("\n" + "=" * 70)
        print("✅ 诊断完成！详细报告已保存")
        print("=" * 70)

    def diagnose_backtest_results(self):
        """诊断1：分析历史回测结果"""
        test_results_files = [
            "test_results_high_vol.json",
            "test_results_ranging_optimization.json",
            "test_results_slippage_comparison.json"
        ]

        results = {
            "status": "✅ 完成",
            "findings": []
        }

        win_rates = []

        for result_file in test_results_files:
            file_path = self.project_root / result_file
            if file_path.exists():
                try:
                    with open(file_path, 'r') as f:
                        data = json.load(f)

                    if 'summary' in data and 'win_rate' in data['summary']:
                        win_rate = data['summary']['win_rate']
                        win_rates.append(win_rate)
                        results["findings"].append({
                            "file": result_file,
                            "win_rate": win_rate,
                            "total_trades": data['summary'].get('total_trades', 0),
                            "profit_factor": data['summary'].get('profit_factor', 0)
                        })
                        print(f"  ✅ {result_file}: 胜率 {win_rate:.2%}")
                except Exception as e:
                    print(f"  ❌ 读取失败 {result_file}: {e}")

        if win_rates:
            avg_win_rate = np.mean(win_rates)
            results["average_win_rate"] = avg_win_rate
            results["min_win_rate"] = min(win_rates)
            results["max_win_rate"] = max(win_rates)

            print(f"  📈 平均胜率: {avg_win_rate:.2%}")
            print(f"  📉 最低胜率: {min(win_rates):.2%}")
            print(f"  📈 最高胜率: {max(win_rates):.2%}")

            if avg_win_rate < 0.65:
                results["issues"] = [f"平均胜率{avg_win_rate:.2%}低于目标65%"]
                print(f"  ⚠️  胜率不达标！目标: 65%, 当前: {avg_win_rate:.2%}")
            else:
                print(f"  ✅ 胜率达标！当前: {avg_win_rate:.2%}")
        else:
            results["issues"] = ["未找到历史回测数据"]
            print("  ⚠️  未找到历史回测数据")

        self.results["diagnostics"]["backtest_results"] = results

    def diagnose_signal_quality(self):
        """诊断2：分析策略信号质量"""
        results = {
            "status": "✅ 完成",
            "findings": []
        }

        # 检查策略信号生成逻辑
        strategy_files = [
            "ema_strategy.py",
            "supertrend_indicator.py",
            "market_scanner.py",
            "technical_indicators.py"
        ]

        print("  检查策略信号生成质量...")

        for strategy_file in strategy_files:
            file_path = self.project_root / "scripts" / strategy_file
            if file_path.exists():
                # 分析信号生成逻辑
                with open(file_path, 'r') as f:
                    content = f.read()

                # 检查是否有确认信号
                has_confirmation = "confirm" in content.lower() or "filter" in content.lower()
                # 检查是否有多个指标
                indicator_count = content.count("indicator") + content.count("ema") + content.count("rsi")

                findings = {
                    "strategy": strategy_file,
                    "has_confirmation": has_confirmation,
                    "indicator_count": indicator_count
                }

                if has_confirmation and indicator_count >= 2:
                    print(f"  ✅ {strategy_file}: 使用确认机制，{indicator_count}个指标")
                elif indicator_count >= 2:
                    print(f"  ⚠️  {strategy_file}: {indicator_count}个指标，但缺少确认机制")
                    results["issues"] = results.get("issues", []) + [f"{strategy_file} 缺少信号确认"]
                else:
                    print(f"  ❌ {strategy_file}: 仅{indicator_count}个指标，信号质量可能不足")
                    results["issues"] = results.get("issues", []) + [f"{strategy_file} 指标数量不足"]

                results["findings"].append(findings)

        self.results["diagnostics"]["signal_quality"] = results

    def diagnose_exit_mechanism(self):
        """诊断3：分析出场机制"""
        results = {
            "status": "✅ 完成",
            "findings": []
        }

        # 检查止损止盈配置
        config_files = ["config.json", "config.yaml"]

        print("  检查出场机制配置...")

        for config_file in config_files:
            file_path = self.project_root / config_file
            if file_path.exists():
                try:
                    with open(file_path, 'r') as f:
                        if config_file.endswith('.json'):
                            config = json.load(f)
                        else:
                            import yaml
                            config = yaml.safe_load(f)

                    # 检查止损止盈比例
                    if 'stop_loss' in config:
                        sl = config['stop_loss']
                        print(f"  📊 止损比例: {sl}%")
                        results["findings"].append({"type": "stop_loss", "value": sl})

                        if sl > 5:
                            print(f"  ⚠️  止损比例过大({sl}%)，可能增加亏损")
                            results["issues"] = results.get("issues", []) + [f"止损比例过大: {sl}%"]

                    if 'take_profit' in config:
                        tp = config['take_profit']
                        print(f"  📊 止盈比例: {tp}%")
                        results["findings"].append({"type": "take_profit", "value": tp})

                        if tp < 2:
                            print(f"  ⚠️  止盈比例过小({tp}%)，可能限制盈利")
                            results["issues"] = results.get("issues", []) + [f"止盈比例过小: {tp}%"]

                        # 计算盈亏比
                        if 'stop_loss' in config:
                            ratio = tp / config['stop_loss']
                            print(f"  📊 盈亏比: {ratio:.2f}")
                            results["findings"].append({"type": "risk_reward_ratio", "value": ratio})

                            if ratio < 1.5:
                                print(f"  ⚠️  盈亏比过低({ratio:.2f})，建议至少1.5")
                                results["issues"] = results.get("issues", []) + [f"盈亏比过低: {ratio:.2f}"]

                except Exception as e:
                    print(f"  ❌ 读取配置失败: {e}")

        self.results["diagnostics"]["exit_mechanism"] = results

    def diagnose_market_regime(self):
        """诊断4：分析市场环境识别"""
        results = {
            "status": "✅ 完成",
            "findings": []
        }

        print("  检查市场环境识别能力...")

        # 检查市场环境识别模块
        regime_files = [
            "market_regime.py",
            "market_regime_optimizer.py",
            "adaptive_regime_switch.py"
        ]

        has_regime_detection = False
        for regime_file in regime_files:
            file_path = self.project_root / "scripts" / regime_file
            if file_path.exists():
                has_regime_detection = True
                with open(file_path, 'r') as f:
                    content = f.read()

                # 检查识别的市场类型
                regimes = []
                if "trend" in content.lower():
                    regimes.append("趋势市场")
                if "ranging" in content.lower():
                    regimes.append("震荡市场")
                if "breakout" in content.lower():
                    regimes.append("突破市场")

                if regimes:
                    print(f"  ✅ {regime_file}: 识别{len(regimes)}种市场环境 - {', '.join(regimes)}")
                    results["findings"].append({"file": regime_file, "regimes": regimes})
                else:
                    print(f"  ⚠️  {regime_file}: 未找到明确的市场环境识别")

        if not has_regime_detection:
            print("  ❌ 未找到市场环境识别模块")
            results["issues"] = ["缺少市场环境识别模块"]

        self.results["diagnostics"]["market_regime"] = results

    def diagnose_strategy_weights(self):
        """诊断5：分析策略权重"""
        results = {
            "status": "✅ 完成",
            "findings": []
        }

        print("  检查策略权重分配...")

        # 检查策略权重配置
        weight_files = [
            "state/strategy_weights.json",
            "meta_controller_weights.json"
        ]

        for weight_file in weight_files:
            file_path = self.project_root / weight_file
            if file_path.exists():
                try:
                    with open(file_path, 'r') as f:
                        weights = json.load(f)

                    if isinstance(weights, dict):
                        # 分析权重分布
                        strategy_count = len(weights)
                        weight_values = list(weights.values())

                        print(f"  📊 {weight_file}: {strategy_count}个策略")
                        print(f"  📊 权重范围: {min(weight_values):.3f} ~ {max(weight_values):.3f}")

                        # 检查权重是否均衡
                        if max(weight_values) > 0.5:
                            print(f"  ⚠️  策略权重过于集中，最大权重: {max(weight_values):.2%}")
                            results["issues"] = results.get("issues", []) + [f"策略权重过于集中"]

                        # 检查权重总和
                        total_weight = sum(weight_values)
                        print(f"  📊 权重总和: {total_weight:.3f}")

                        if abs(total_weight - 1.0) > 0.01:
                            print(f"  ⚠️  权重总和不为1.0: {total_weight:.3f}")
                            results["issues"] = results.get("issues", []) + [f"权重总和不为1.0"]

                        results["findings"].append({
                            "file": weight_file,
                            "strategy_count": strategy_count,
                            "weight_range": (min(weight_values), max(weight_values)),
                            "total_weight": total_weight
                        })

                except Exception as e:
                    print(f"  ❌ 读取权重文件失败: {e}")

        self.results["diagnostics"]["strategy_weights"] = results

    def diagnose_risk_control(self):
        """诊断6：分析风控影响"""
        results = {
            "status": "✅ 完成",
            "findings": []
        }

        print("  检查风控规则影响...")

        # 检查风控配置
        config_file = self.project_root / "config.json"
        if config_file.exists():
            try:
                with open(config_file, 'r') as f:
                    config = json.load(f)

                # 检查风控规则
                risk_rules = config.get('risk_rules', {})

                if 'max_position_size' in risk_rules:
                    print(f"  📊 最大持仓比例: {risk_rules['max_position_size']}%")

                if 'max_daily_loss' in risk_rules:
                    print(f"  📊 最大日亏损: {risk_rules['max_daily_loss']}%")

                if 'max_consecutive_losses' in risk_rules:
                    print(f"  📊 最大连续亏损: {risk_rules['max_consecutive_losses']}次")

                    if risk_rules['max_consecutive_losses'] < 3:
                        print(f"  ⚠️  最大连续亏损限制过严，可能错失机会")
                        results["issues"] = results.get("issues", []) + ["连续亏损限制过严"]

                results["findings"].append({
                    "risk_rules": risk_rules
                })

            except Exception as e:
                print(f"  ❌ 读取风控配置失败: {e}")

        self.results["diagnostics"]["risk_control"] = results

    def diagnose_configuration(self):
        """诊断7：分析配置合理性"""
        results = {
            "status": "✅ 完成",
            "findings": []
        }

        print("  检查配置参数合理性...")

        # 读取主配置
        config_file = self.project_root / "config.json"
        if config_file.exists():
            try:
                with open(config_file, 'r') as f:
                    config = json.load(f)

                # 检查关键参数
                checks = [
                    ("leverage", "杠杆倍数", lambda x: x <= 10),
                    ("position_size", "持仓比例", lambda x: 0.01 <= x <= 1.0),
                    ("min_order_size", "最小订单", lambda x: x > 0),
                ]

                for key, name, validator in checks:
                    if key in config:
                        value = config[key]
                        valid = validator(value)
                        if valid:
                            print(f"  ✅ {name}: {value}")
                        else:
                            print(f"  ⚠️  {name}: {value} - 可能不合理")
                            results["issues"] = results.get("issues", []) + [f"{name}不合理: {value}"]

                        results["findings"].append({key: value})

            except Exception as e:
                print(f"  ❌ 读取配置失败: {e}")

        self.results["diagnostics"]["configuration"] = results

    def generate_summary_report(self):
        """诊断8：生成综合报告"""
        print("\n" + "=" * 70)
        print("📋 综合诊断报告")
        print("=" * 70)

        # 汇总所有问题
        all_issues = []
        for category, result in self.results["diagnostics"].items():
            if "issues" in result:
                for issue in result["issues"]:
                    all_issues.append({
                        "category": category,
                        "issue": issue
                    })

        if all_issues:
            print(f"\n❌ 发现 {len(all_issues)} 个问题:\n")
            for i, issue in enumerate(all_issues, 1):
                print(f"{i}. [{issue['category']}] {issue['issue']}")
        else:
            print("\n✅ 未发现明显问题")

        # 胜率评估
        backtest_results = self.results["diagnostics"].get("backtest_results", {})
        avg_win_rate = backtest_results.get("average_win_rate", 0)

        print(f"\n📊 当前平均胜率: {avg_win_rate:.2%}")
        print(f"🎯 目标胜率: 65%")

        if avg_win_rate < 0.65:
            gap = 0.65 - avg_win_rate
            print(f"⚠️  胜率差距: {gap:.2%} (需提升{gap*100:.1f}个百分点)")

            # 提供优化建议
            print(f"\n💡 优化建议:")
            print(f"1. 提高信号质量 - 增加确认机制，使用多指标融合")
            print(f"2. 优化出场机制 - 调整止盈止损比例，使用动态出场")
            print(f"3. 引入市场环境识别 - 根据趋势/震荡市场调整策略")
            print(f"4. 优化策略权重 - 根据历史表现动态分配权重")
            print(f"5. 改进风险管理 - 合理设置风控参数，避免过严/过松")

        self.results["summary"] = {
            "total_issues": len(all_issues),
            "issues": all_issues,
            "current_win_rate": avg_win_rate,
            "target_win_rate": 0.65,
            "needs_improvement": avg_win_rate < 0.65
        }

    def save_results(self):
        """保存诊断结果"""
        output_path = self.project_root / "winrate_diagnostics_report.json"
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)

        print(f"\n📄 诊断报告已保存: {output_path}")


if __name__ == "__main__":
    diagnostics = WinRateDiagnostics()
    diagnostics.diagnose_all()
