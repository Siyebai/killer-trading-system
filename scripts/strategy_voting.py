#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("strategy_voting")
except ImportError:
    import logging
    logger = logging.getLogger("strategy_voting")
"""
多策略投票聚合模块
将多个子策略的交易信号聚合为统一决策
"""

import argparse
import json
import sys
from typing import List, Dict


def simple_voting(signals: List[Dict]) -> Dict:
    """简单多数投票"""
    votes = {"buy": 0, "sell": 0, "hold": 0}
    for sig in signals:
        signal = sig.get("signal", "hold").lower()
        if signal in votes:
            votes[signal] += 1

    decision = max(votes, key=votes.get)
    confidence = votes[decision] / len(signals) if signals else 0

    return {
        "decision": decision,
        "confidence": confidence,
        "method": "simple_voting",
        "votes": votes
    }


def weighted_voting(signals: List[Dict]) -> Dict:
    """加权投票（基于策略置信度）"""
    scores = {"buy": 0.0, "sell": 0.0, "hold": 0.0}
    weights = {"buy": 0, "sell": 0, "hold": 0}

    for sig in signals:
        signal = sig.get("signal", "hold").lower()
        confidence = sig.get("confidence", 0.5)
        if signal in scores:
            scores[signal] += confidence
            weights[signal] += 1

    # 归一化
    for key in scores:
        scores[key] = scores[key] / weights[key] if weights[key] > 0 else 0

    decision = max(scores, key=scores.get)
    confidence = scores[decision]

    return {
        "decision": decision,
        "confidence": confidence,
        "method": "weighted_voting",
        "scores": scores
    }


def consenus_voting(signals: List[Dict]) -> Dict:
    """共识投票（要求高一致性的决策）"""
    votes = {"buy": 0, "sell": 0, "hold": 0}
    for sig in signals:
        signal = sig.get("signal", "hold").lower()
        if signal in votes:
            votes[signal] += 1

    threshold = len(signals) * 0.6  # 60%共识阈值
    decision = "hold"  # 默认持有

    for sig_type, count in votes.items():
        if count >= threshold:
            decision = sig_type
            break

    confidence = votes[decision] / len(signals) if signals else 0

    return {
        "decision": decision,
        "confidence": confidence,
        "method": "consensus_voting",
        "votes": votes,
        "threshold": threshold
    }


def main():
    parser = argparse.ArgumentParser(description="多策略投票聚合")
    parser.add_argument("--signals", required=True, help="策略信号列表(JSON格式)")
    parser.add_argument("--method", default="weighted",
                       choices=["simple", "weighted", "consensus"],
                       help="投票方法")

    args = parser.parse_args()

    try:
        signals = json.loads(args.signals)

        if not isinstance(signals, list):
            logger.info((json.dumps({)
                "status": "error",
                "message": "signals必须是列表格式"
            }, ensure_ascii=False))
            sys.exit(1)

        if not signals:
            logger.info((json.dumps({)
                "status": "error",
                "message": "策略信号列表不能为空"
            }, ensure_ascii=False))
            sys.exit(1)

        # 根据方法选择投票算法
        if args.method == "simple":
            result = simple_voting(signals)
        elif args.method == "weighted":
            result = weighted_voting(signals)
        elif args.method == "consensus":
            result = consenus_voting(signals)
        else:
            raise ValueError(f"未知的投票方法: {args.method}")

        output = {
            "status": "success",
            "result": result,
            "input_count": len(signals)
        }

        logger.info(json.dumps(output, ensure_ascii=False, indent=2))

    except json.JSONDecodeError as e:
        logger.error((json.dumps({)
            "status": "error",
            "message": f"JSON解析失败: {str(e)}"
        }, ensure_ascii=False))
        sys.exit(1)
    except Exception as e:
        logger.error((json.dumps({)
            "status": "error",
            "message": f"处理失败: {str(e)}"
        }, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
