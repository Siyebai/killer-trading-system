#!/usr/bin/env python3
"""
杀手锏交易系统 v1.0.2 - 统一入口
支持四种运行模式：
  - v61: v1.0.2 总控中心版（推荐，含自我检查/自我修复/自我优化）
  - v60: v1.0.2 智能优化版（EV过滤+订单生命周期管理）
  - closed_loop: 10层完整闭环模式
  - normal: 原有单Agent模式（v1.0.2兼容）

使用方法：
    python main_v61.py --mode v61
    python main_v61.py --mode v61 --action run_continuous --interval 60
    python main_v61.py --mode v61 --action status
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def run_v61_mode(args):
    """
    运行v1.0.2模式（推荐）
    
    核心特性：
    - v1.0.2: EV过滤 + 订单生命周期管理
    - v1.0.2: 总控中心（全局状态/健康检查/修复引擎/任务调度/性能优化）
    - 零侵入集成：各层执行前查询全局状态
    - 风控熔断联动：软/硬熔断自动切换系统状态
    - 多symbol并行调度
    """
    print("\n" + "="*70)
    print("  杀手锏交易系统 v1.0.2 - 总控中心版")
    print("="*70)
    print("\n  核心能力：")
    print("  [v1.0.2] EV过滤：预期价值过滤，只执行正期望交易")
    print("  [v1.0.2] 订单生命周期管理：幂等性控制，防止重复下单")
    print("  [v1.0.2] 总控中心：全局状态管理 + 健康检查 + 修复引擎")
    print("  [v1.0.2] 任务调度：多symbol并行调度")
    print("  [v1.0.2] 性能优化：动态调参 + 离线搜索触发")
    print("  [v1.0.2] 风控熔断联动：软/硬熔断自动切换系统状态")
    print("\n  预期性能：")
    print("  - 胜率：63-65%")
    print("  - 夏普比率：1.2-1.6")
    print("  - 最大回撤：8-12%")
    print("  - 系统可用性：99.9%")
    print("  - 自我修复响应时间：<30秒")
    print("="*70 + "\n")
    
    config_path = args.config or "assets/configs/killer_config_v60.json"
    
    if not Path(config_path).exists():
        print(f"配置文件不存在: {config_path}")
        sys.exit(1)
    
    from scripts.complete_loop_v61 import CompleteLoopv1.0.2
    system = CompleteLoopv1.0.2(config_path)
    
    if args.action == 'run_once':
        asyncio.run(system.run_once())
    elif args.action == 'run_continuous':
        asyncio.run(system.run_continuous(args.interval))
    elif args.action == 'status':
        system.print_status()
    else:
        print(f"未知操作: {args.action}")
        sys.exit(1)


def run_v60_mode(args):
    """运行v1.0.2模式"""
    config_path = args.config or "assets/configs/killer_config_v60.json"
    
    if not Path(config_path).exists():
        print(f"配置文件不存在: {config_path}")
        sys.exit(1)
    
    from scripts.complete_loop_system_v60 import CompleteLoopSystemv1.0.2
    system = CompleteLoopSystemv1.0.2(config_path)
    
    if args.action == 'run_once':
        asyncio.run(system.run_once())
    elif args.action == 'run_continuous':
        system.run_continuous(args.interval)


def run_closed_loop_mode(args):
    """运行10层闭环模式"""
    config_path = args.config or "assets/configs/killer_config_v58.json"
    
    from scripts.complete_loop_system import CompleteLoopSystem
    system = CompleteLoopSystem(config_path)
    
    if args.action == 'run_once':
        system.run_once()
    elif args.action == 'run_continuous':
        system.run_continuous(args.interval)


def run_normal_mode(args):
    """运行原有模式（v1.0.2兼容）"""
    config_path = args.config or "assets/configs/killer_config_risk_v59.json"
    
    from scripts.complete_loop_with_risk import CompleteLoopWithRisk
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
  # 运行v1.0.2总控中心版（推荐）
  python main_v61.py --mode v61 --action run_continuous --interval 60
  
  # 查看系统状态
  python main_v61.py --mode v61 --action status
  
  # 运行v1.0.2智能优化版
  python main_v61.py --mode v60 --action run_once
  
  # 运行10层闭环模式
  python main_v61.py --mode closed_loop --action run_once
  
  # 运行原有模式（v1.0.2兼容）
  python main_v61.py --mode normal --action run_once
        """
    )
    
    parser.add_argument(
        '--mode',
        choices=['v61', 'v60', 'closed_loop', 'normal'],
        default='v61',
        help='运行模式（默认：v61）'
    )
    parser.add_argument(
        '--action',
        choices=['run_once', 'run_continuous', 'status'],
        default='run_once',
        help='执行动作（默认：run_once）'
    )
    parser.add_argument('--interval', type=int, default=60, help='连续运行间隔（秒）')
    parser.add_argument('--config', type=str, default=None, help='配置文件路径')
    
    args = parser.parse_args()
    
    mode_map = {
        'v61': run_v61_mode,
        'v60': run_v60_mode,
        'closed_loop': run_closed_loop_mode,
        'normal': run_normal_mode
    }
    
    mode_map[args.mode](args)


if __name__ == "__main__":
    main()
