#!/usr/bin/env python3
"""
完美工业级Round 3 - 批量修复JSON语法错误 v2
只修复双重括号，不替换字面量\n
"""

from pathlib import Path
import ast


def fix_double_brackets_only(file_path: Path) -> dict:
    """只修复双重括号错误"""
    result = {"fixed": False, "errors": []}

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            original_content = f.read()

        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        modified = False
        modifications = []

        for i, line in enumerate(lines):
            original_line = lines[i]
            modified_line = original_line

            # 只修复双重括号
            patterns_to_fix = [
                ('logger.info((json.dumps({', 'logger.info(json.dumps({)'),
                ('logger.error((json.dumps({', 'logger.error(json.dumps({)'),
                ('logger.warning((json.dumps({', 'logger.warning(json.dumps({)'),
                ('logger.debug((json.dumps({', 'logger.debug(json.dumps({)'),
                ('logger.info((json.dumps([', 'logger.info(json.dumps([')),
                ('logger.error((json.dumps([', 'logger.error(json.dumps([')),
            ]

            for pattern, replacement in patterns_to_fix:
                if pattern in modified_line:
                    modified_line = modified_line.replace(pattern, replacement)
                    modifications.append(f"第{i+1}行: 双重括号修复")
                    modified = True
                    break

            if modified_line != original_line:
                lines[i] = modified_line

        if modified:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)

            try:
                with open(file_path, 'r') as f:
                    ast.parse(f.read())
                result["fixed"] = True
                result["modifications"] = modifications
            except SyntaxError as e:
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
    scripts_dir = Path('scripts')

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

    fixed_count = 0
    failed_count = 0
    skipped_count = 0

    for file_path in error_files:
        print(f"\n处理: {file_path.name}")

        result = fix_double_brackets_only(file_path)

        if result["fixed"]:
            fixed_count += 1
            print(f"✅ 修复成功")
            for mod in result.get("modifications", []):
                print(f"   - {mod}")
        elif result["errors"]:
            failed_count += 1
            print(f"❌ 修复失败")
            for err in result["errors"][:2]:
                print(f"   - {err}")
        else:
            skipped_count += 1
            print(f"⏭️ 跳过")

    print("\n" + "=" * 80)
    print(f"修复统计:")
    print(f"  成功: {fixed_count}")
    print(f"  失败: {failed_count}")
    print(f"  跳过: {skipped_count}")
    print(f"  总计: {len(error_files)}")
    print("=" * 80)

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
        print("\n🎉 语法错误修复接近完成！")
    elif remaining_errors < len(error_files):
        print(f"\n✅ 部分成功：已修复 {len(error_files) - remaining_errors}/{len(error_files)} 个文件")
    else:
        print("\n⚠️ 未能修复任何文件")


if __name__ == "__main__":
    main()
