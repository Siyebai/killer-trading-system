# [ARCHIVED by Round 6 Integration - 2026-04-30]
# Reason: No active callers / Superseded by production module

#!/usr/bin/env python3
"""
完美工业级Round 3 - 批量修复JSON语法错误
基于验证成功的方法：双重括号修复 + 字面量\n替换
"""

from pathlib import Path
import ast


def fix_json_errors(file_path: Path) -> dict:
    """
    修复JSON语法错误

    Returns:
        dict: {"fixed": bool, "errors": list}
    """
    result = {"fixed": False, "errors": []}

    try:
        # 备份原文件
        with open(file_path, 'r', encoding='utf-8') as f:
            original_content = f.read()

        # 读取行
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        modified = False
        modifications = []

        for i, line in enumerate(lines):
            original_line = lines[i]
            modified_line = original_line

            # 修复1: 双重括号 logger.info((json.dumps({ -> logger.info(json.dumps({
            patterns_to_fix = [
                ('logger.info((json.dumps({', 'logger.info(json.dumps({)'),
                ('logger.error((json.dumps({', 'logger.error(json.dumps({)'),
                ('logger.warning((json.dumps({', 'logger.warning(json.dumps({)'),
                ('logger.debug((json.dumps({', 'logger.debug(json.dumps({)'),
                ('logger.info((json.dumps([', 'logger.info(json.dumps(['),
                ('logger.error((json.dumps([', 'logger.error(json.dumps(['),
            ]

            for pattern, replacement in patterns_to_fix:
                if pattern in modified_line:
                    modified_line = modified_line.replace(pattern, replacement)
                    modifications.append(f"第{i+1}行: 双重括号修复")

            # 修复2: 字面量 \n -> 真正的换行符（仅在非注释的logger/json.dumps调用中）
            if r'\n' in modified_line and ('json.dumps' in modified_line or 'logger.' in modified_line):
                # 确保不是注释
                if not modified_line.strip().startswith('#'):
                    # 检查\n是否在logger调用中
                    if any(level in modified_line for level in ['logger.info', 'logger.error', 'logger.warning', 'logger.debug']):
                        # 替换字面量\n为真正的换行
                        modified_line = modified_line.replace(r'\n', '\n')
                        modifications.append(f"第{i+1}行: \\n -> 换行")

            if modified_line != original_line:
                lines[i] = modified_line
                modified = True

        if modified:
            # 写入修复后的内容
            with open(file_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)

            # 验证修复结果
            try:
                with open(file_path, 'r') as f:
                    ast.parse(f.read())
                result["fixed"] = True
                result["modifications"] = modifications
            except SyntaxError as e:
                # 回滚
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(original_content)
                result["errors"].append(f"修复后仍有错误: {e.msg} (行{e.lineno})")

        else:
            result["errors"].append("未识别的错误模式")

    except Exception as e:
        result["errors"].append(f"修复过程异常: {e}")

    return result


def main():
    """主函数"""
    from pathlib import Path

    scripts_dir = Path('scripts')

    # 扫描所有有语法错误的文件
    error_files = []
    for py_file in scripts_dir.rglob('*.py'):
        if '__pycache__' in str(py_file):
            continue
        try:
            with open(py_file) as f:
                ast.parse(f.read())
        except SyntaxError:
            error_files.append(py_file)

    print(f"发现 {len(error_files)} 个有语法错误的文件\n")
    print("=" * 80)

    # 逐个修复
    fixed_count = 0
    failed_count = 0
    skipped_count = 0

    for file_path in error_files:
        print(f"\n处理: {file_path.name}")

        result = fix_json_errors(file_path)

        if result["fixed"]:
            fixed_count += 1
            print(f"✅ 修复成功")
            for mod in result.get("modifications", []):
                print(f"   - {mod}")
        elif result["errors"]:
            failed_count += 1
            print(f"❌ 修复失败")
            for err in result["errors"]:
                print(f"   - {err}")
        else:
            skipped_count += 1
            print(f"⏭️ 跳过")

    # 最终统计
    print("\n" + "=" * 80)
    print(f"修复统计:")
    print(f"  成功: {fixed_count}")
    print(f"  失败: {failed_count}")
    print(f"  跳过: {skipped_count}")
    print(f"  总计: {len(error_files)}")
    print("=" * 80)

    # 重新扫描验证
    remaining_errors = 0
    for py_file in scripts_dir.rglob('*.py'):
        if '__pycache__' in str(py_file):
            continue
        try:
            with open(py_file) as f:
                ast.parse(f.read())
        except SyntaxError:
            remaining_errors += 1

    print(f"\n剩余语法错误文件数: {remaining_errors}")

    if remaining_errors < 5:
        print("\n🎉 语法错误修复完成！剩余文件需要人工处理。")
    elif remaining_errors < len(error_files):
        print(f"\n✅ 部分成功：已修复 {len(error_files) - remaining_errors}/{len(error_files)} 个文件")
    else:
        print("\n⚠️ 未能修复任何文件，需要人工处理")


if __name__ == "__main__":
    main()
