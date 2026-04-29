#!/usr/bin/env python3
"""
批量修复所有\转义符 - 最终彻底版
"""

from pathlib import Path


def fix_all_escapes(file_path: Path) -> bool:
    """修复所有转义符"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        original = content

        # 修复: \n -> 真正的换行符
        content = content.replace('\\n', '\n')

        # 修复: \t -> 真正的制表符
        content = content.replace('\\t', '\t')

        if content != original:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True

        return False

    except Exception as e:
        print(f"修复失败 {file_path}: {e}")
        return False


def main():
    """主函数"""
    import ast

    error_files = []
    for py_file in Path('scripts').rglob('*.py'):
        if '__pycache__' in str(py_file):
            continue
        try:
            with open(py_file) as f:
                ast.parse(f.read())
        except:
            error_files.append(py_file)

    print(f"发现 {len(error_files)} 个有语法错误的文件\n")

    # 逐个修复
    fixed_count = 0
    for py_file in error_files:
        if fix_all_escapes(py_file):
            fixed_count += 1
            print(f"✓ 修复: {py_file.name}")

    # 修复双重括号
    fixed_bracket = 0
    for py_file in Path('scripts').rglob('*.py'):
        if '__pycache__' in str(py_file):
            continue

        try:
            with open(py_file, 'r', encoding='utf-8') as f:
                content = f.read()
            original = content

            # 修复双重括号
            patterns = [
                ('logger.info((json.dumps({', 'logger.info(json.dumps({)'),
                ('logger.error((json.dumps({', 'logger.error(json.dumps({)'),
                ('logger.warning((json.dumps({', 'logger.warning(json.dumps({)'),
                ('logger.debug((json.dumps({', 'logger.debug(json.dumps({)')
            ]

            for pattern, replacement in patterns:
                content = content.replace(pattern, replacement)

            if content != original:
                with open(py_file, 'w', encoding='utf-8') as f:
                    f.write(content)
                fixed_bracket += 1

        except Exception:
            pass

    print(f"\n修复转义符: {fixed_count} 个文件")
    print(f"修复双重括号: {fixed_bracket} 个文件")

    # 验证
    remaining = 0
    for py_file in error_files:
        try:
            with open(py_file) as f:
                ast.parse(f.read())
        except:
            remaining += 1

    print(f"仍有错误: {remaining} 个文件")

    if remaining == 0:
        print("\n🎉🎉🎉 所有语法错误已修复！ 🎉🎉🎉")
    else:
        print(f"\n⚠️ 仍有 {remaining} 个文件需要进一步处理")


if __name__ == "__main__":
    main()
