#!/usr/bin/env python3
"""
杀手锏交易系统 v1.0.2 - 统一入口
支持三种运行模式：
  - normal: 原有单Agent模式（v1.0.2兼容）
  - closed_loop: 10层完整闭环模式
  - v60: v1.0.2智能优化版（EV过滤 + 订单生命周期管理）

使用方法：
    python main_v60.py --mode v60
    python main_v60.py --mode v60 --action run_continuous --interval 60
"""

import argparse
import asyncio
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from scripts.complete_loop_system_v60 import CompleteLoopSystemv1.0.2
from scripts.complete_loop_with_risk import CompleteLoopWithRisk
from scripts.complete_loop_system import CompleteLoopSystem


def run_v60_mode(args):
    """
    运行v1.0.2模式（推荐）
    
    核心特性：
    - EV过滤：预期价值过滤，提升胜率至63-65%
    - 订单生命周期管理：幂等性控制，防止重复下单
    - TTL超时撤单：默认800ms TTL
    - 11层完整闭环 + 风控层
    """
    print("\n" + "="*60)
    print("🚀 杀手锏交易系统 v1.0.2 - 智能优化版")
    print("="*60)
    print("\n✨ 核心特性：")
    print("  • EV过滤：预期价值过滤，只执行正期望交易")
    print("  • 订单生命周期管理：幂等性控制，防止重复下单")
    print("  • TTL超时撤单：默认800ms TTL，自动撤单")
    print("  • 11层完整闭环 + 风控层（13规则 + 分级熔断）")
    print("\n📊 预期性能：")
    print("  • 胜率：63-65%")
    print("  • 夏普比率：1.2-1.6")
    print("  • 最大回撤：8-12%")
    print("  • 系统可用性：99.9%")
    print("="*60 + "\n")
    
    config_path = args.config or "assets/configs/killer_config_v60.json"
    
    # 检查配置文件
    if not Path(config_path).exists():
        print(f"❌ 配置文件不存在: {config_path}")
        print(f"💡 提示：请确保配置文件存在或使用 --config 指定路径")
        sys.exit(1)
    
    # 创建v1.0.2系统
    system = CompleteLoopSystemv1.0.2(config_path)
    
    # 执行
    if args.action == 'run_once':
        asyncio.run(system.run_once())
    elif args.action == 'run_continuous':
        system.run_continuous(args.interval)
    else:
        print(f"❌ 未知操作: {args.action}")
        sys.exit(1)


def run_closed_loop_mode(args):
    """运行10层闭环模式"""
    print("\n" + "="*60)
    print("🚀 杀手锏交易系统 - 10层完整闭环模式")
    print("="*60 + "\n")
    
    config_path = args.config or "assets/configs/killer_config_v58.json"
    system = CompleteLoopSystem(config_path)
    
    if args.action == 'run_once':
        system.run_once()
    elif args.action == 'run_continuous':
        system.run_continuous(args.interval)


def run_normal_mode(args):
    """运行原有单Agent模式（v1.0.2兼容）"""
    print("\n" + "="*60)
    print("🚀 杀手锏交易系统 - 单Agent模式（v1.0.2兼容）")
    print("="*60 + "\n")
    
    config_path = args.config or "assets/configs/killer_config_risk_v59.json"
    system = CompleteLoopWithRisk(config_path)
    
    if args.action == 'run_once':
        asyncio.run(system.run_once())
    elif args.action == 'run_continuous':
        system.run_continuous(args.interval)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="杀手锏交易系统 v1.0.2 - 统一入口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例：
  # 运行v1.0.2智能优化版（推荐）
  python main_v60.py --mode v60 --action run_once
  
  # 连续运行v1.0.2（间隔60秒）
  python main_v60.py --mode v60 --action run_continuous --interval 60
  
  # 运行10层闭环模式
  python main_v60.py --mode closed_loop --action run_once
  
  # 运行原有模式（v1.0.2兼容）
  python main_v60.py --mode normal --action run_once
  
  # 使用自定义配置
  python main_v60.py --mode v60 --config assets/configs/killer_config_v60.json
        """
    )
    
    parser.add_argument(
        '--mode',
        choices=['v60', 'closed_loop', 'normal'],
        default='v60',
        help='运行模式（默认：v60）'
    )
    
    parser.add_argument(
        '--action',
        choices=['run_once', 'run_continuous'],
        default='run_once',
        help='执行动作（默认：run_once）'
    )
    
    parser.add_argument(
        '--interval',
        type=int,
        default=60,
        help='连续运行间隔（秒，默认：60）'
    )
    
    parser.add_argument(
        '--config',
        type=str,
        default=None,
        help='配置文件路径（可选）'
    )
    
    args = parser.parse_args()
    
    # 根据模式执行
    if args.mode == 'v60':
        run_v60_mode(args)
    elif args.mode == 'closed_loop':
        run_closed_loop_mode(args)
    else:  # normal
        run_normal_mode(args)


if __name__ == "__main__":
    main()
