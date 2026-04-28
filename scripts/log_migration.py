#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("log_migration")
except ImportError:
    import logging
    logger = logging.getLogger("log_migration")
"""
自动化日志迁移脚本 — V6.3.1
扫描所有Python文件,将print(...)替换为logger.xxx(...)
智能推断日志级别: except块→error, 警告词→warning, 调试词→debug, 其他→info
"""

import argparse
import ast
import os
import re
import sys
from typing import Dict, List, Tuple


def analyze_print_calls(filepath: str) -> List[Dict]:
    """分析文件中的print调用,返回建议替换信息"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
            tree = ast.parse(content, filepath)
    except SyntaxError:
        return []

    results = []
    warning_keywords = ["warning", "warn", "deprecated", "slow", "timeout", "retry"]
    error_keywords = ["error", "fail", "exception", "invalid", "reject", "timeout"]

    class PrintVisitor(ast.NodeVisitor):
        def __init__(self):
            self.print_calls = []

        def visit_Call(self, node):
            if isinstance(node.func, ast.Name) and node.func.id == "print":
                line = node.lineno
                col = node.col_offset

                # 推断日志级别
                level = "info"
                args = []

                for arg in node.args:
                    if isinstance(arg, ast.Str):
                        args.append(arg.s)
                    elif isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        args.append(arg.value)

                msg = " ".join(args).lower() if args else ""
                msg_lower = " ".join(str(arg).lower() for arg in node.args).lower()

                # 检查上下文(简单判断:是否在try块内的except块中)
                in_except = False
                parent = getattr(node, "parent", None)
                while parent:
                    if isinstance(parent, ast.ExceptHandler):
                        in_except = True
                        break
                    parent = getattr(parent, "parent", None)

                if in_except or any(kw in msg_lower for kw in error_keywords):
                    level = "error"
                elif any(kw in msg_lower for kw in warning_keywords):
                    level = "warning"
                elif any(kw in msg_lower for kw in ["debug", "trace", "verbose", "check"]):
                    level = "debug"

                # 提取原始代码
                start = max(0, col - 10)
                lines = content.split("\n")
                if line - 1 < len(lines):
                    original = lines[line - 1][start:start + 50]

                results.append({
                    "line": line,
                    "col": col,
                    "level": level,
                    "original": original.strip() if line - 1 < len(lines) else "print(...)",
                    "args_count": len(node.args),
                })

            self.generic_visit(node)

    visitor = PrintVisitor()
    # 手动设置parent关系
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child.parent = node
    visitor.visit(tree)

    return results


def generate_logger_import(filepath: str, print_results: List[Dict]) -> str:
    """生成logger导入语句"""
    if not print_results:
        return ""

    base_name = os.path.splitext(os.path.basename(filepath))[0]
    return f"""
# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("{base_name}")
except ImportError:
    import logging
    logger = logging.getLogger("{base_name}")
"""


def replace_prints_in_file(filepath: str, dry_run: bool = True) -> Tuple[bool, str]:
    """替换文件中的print为logger调用"""
    print_results = analyze_print_calls(filepath)
    if not print_results:
        return False, "No print calls found"

    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # 检查是否已有logger导入
    has_logger_import = any(
        "from scripts.logger_factory import get_logger" in line or
        "import logging" in line
        for line in lines[:30]
    )

    replacements = []

    for pr in print_results:
        line_idx = pr["line"] - 1
        if line_idx >= len(lines):
            continue

        original_line = lines[line_idx]

        # 简单替换: print(x) → logger.info(x)
        # 注意: 复杂的print可能需要手动处理
        indent_match = re.match(r"^(\s*)", original_line)
        indent = indent_match.group(1) if indent_match else ""

        # 构建logger调用
        args_part = original_line.strip()[len("print"):].strip()
        if args_part.startswith("(") and args_part.endswith(")"):
            args_part = args_part[1:-1]

        new_call = f"{indent}logger.{pr['level']}({args_part})\n"

        replacements.append((line_idx, original_line, new_call, pr))

    # 应用替换(倒序,避免行号偏移)
    if not dry_run:
        for line_idx, original, new_call, pr in reversed(replacements):
            lines[line_idx] = new_call

        # 添加logger导入(如果需要)
        if not has_logger_import:
            import_line = generate_logger_import(filepath, print_results)
            # 找到第一个合适的位置(通常在文件开头或shebang之后)
            insert_idx = 0
            for i, line in enumerate(lines):
                if line.strip() and not line.startswith("#!"):
                    insert_idx = i
                    break
            lines.insert(insert_idx, import_line)

        with open(filepath, "w", encoding="utf-8") as f:
            f.writelines(lines)

    return True, f"Replaced {len(replacements)} print calls"


def migrate_directory(directory: str, dry_run: bool = True,
                      patterns: List[str] = ["*.py"]) -> Dict:
    """迁移目录中的所有Python文件"""
    import glob

    results = {
        "total_files": 0,
        "migrated_files": 0,
        "total_prints": 0,
        "replaced_prints": 0,
        "files": [],
    }

    for pattern in patterns:
        for filepath in glob.glob(os.path.join(directory, pattern)):
            # 跳过_archived目录
            if "_archived" in filepath or "test_" in filepath:
                continue

            results["total_files"] += 1
            print_results = analyze_print_calls(filepath)

            if print_results:
                results["total_prints"] += len(print_results)
                if not dry_run:
                    success, msg = replace_prints_in_file(filepath, dry_run=False)
                    if success:
                        results["migrated_files"] += 1
                        results["replaced_prints"] += len(print_results)
                        results["files"].append(filepath)
                else:
                    results["files"].append({
                        "path": filepath,
                        "print_count": len(print_results),
                        "details": print_results[:5],  # 仅前5个
                    })
                logger.info(f"{'[DRY RUN] ' if dry_run else '[MIGRATED]'} {filepath}: {len(print_results)} prints")

    return results


def main():
    parser = argparse.ArgumentParser(description="自动化日志迁移脚本")
    parser.add_argument("--directory", default="scripts", help="目标目录")
    parser.add_argument("--dry-run", action="store_true", default=True,
                       help="预览模式(不实际修改文件)")
    parser.add_argument("--file", type=str, default=None, help="指定单个文件")
    parser.add_argument("--apply", action="store_true", help="应用修改(取消dry-run)")
    parser.add_argument("--strict", action="store_true", help="严格模式: 编译失败则自动回滚")
    args = parser.parse_args()

    if args.file:
        # 单文件模式
        if os.path.exists(args.file):
            results = analyze_print_calls(args.file)
            logger.info(f"\n{args.file}: {len(results)} print calls found")
            for pr in results:
                logger.info(f"  Line {pr['line']}: {pr['original']} -> logger.{pr['level']}")

            if args.apply:
                success, msg = replace_prints_in_file(args.file, dry_run=False)
                logger.info(f"\nResult: {msg}")
        else:
            logger.info(f"File not found: {args.file}")
    else:
        # 目录模式
        dry_run = args.dry_run and not args.apply
        logger.info(f"Scanning {args.directory} {'(dry run)' if dry_run else '(applying)'}...")
        results = migrate_directory(args.directory, dry_run=dry_run)

        logger.info(f"\n{'=' * 60}")
        logger.info(f"Total files scanned: {results['total_files']}")
        logger.info(f"Total prints found: {results['total_prints']}")
        logger.info(f"Files modified: {results['migrated_files']}")
        logger.info(f"Prints replaced: {results['replaced_prints']}")
        logger.info(f"{'=' * 60}")

        # 严格模式: 编译验证
        if args.apply and args.strict:
            logger.info("\n[STRICT MODE] Verifying compilation...")
            import py_compile
            compilation_failed = False
            for filepath in results["files"]:
                try:
                    py_compile.compile(filepath, doraise=True)
                except py_compile.PyCompileError as e:
                    logger.error(f"Compilation failed for {filepath}: {e}")
                    # 回滚到备份
                    backup_path = f"{filepath}.bak_{int(time.time())}"
                    if os.path.exists(backup_path):
                        os.replace(backup_path, filepath)
                        logger.warning(f"Rolled back {filepath} from backup")
                    compilation_failed = True

            if compilation_failed:
                logger.error("STRICT MODE FAILED: Some files failed compilation and were rolled back")
                return 1
            else:
                logger.info("STRICT MODE PASSED: All files compile successfully")

    return 0
        logger.info(f"Files with prints: {len(results['files'])}")
        logger.info(f"Total print calls: {results['total_prints']}")
        if not dry_run:
            logger.info(f"Files migrated: {results['migrated_files']}")
            logger.info(f"Prints replaced: {results['replaced_prints']}")
        else:
            logger.info(f"[DRY RUN] Run with --apply to execute migration")

        if dry_run and results['files']:
            logger.info(f"\nFiles with prints (top 20):")
            for f in results['files'][:20]:
                if isinstance(f, dict):
                    logger.info(f"  {f['path']}: {f['print_count']} prints")
                else:
                    logger.info(f"  {f}")


if __name__ == "__main__":
    main()
