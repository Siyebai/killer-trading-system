#!/usr/bin/env python3
"""
批量修复JSON语法错误 - 处理字面量\n问题
"""

from pathlib import Path


def fix_json_literal_newline(file_path: Path) -> bool:
    """修复字面量\n问题"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        original = content

        # 修复: logger.info((json.dumps({\n        "status": -> logger.info(json.dumps({\n        "status":
        # 将字面量\n替换为真正的换行符
        import re

        # 模式: logger.xxx((json.dumps({\n        "
        pattern = r'(logger\.(info|error|warning|debug)\(\()json\.dumps\(\{\\n\s+"'
        replacement = r'\1json\.dumps({\n        "'
        content = re.sub(pattern, replacement, content)

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

    print(f"发现 {len(error_files)} 个有语法错误的文件")

    # 先修复字面量\n问题
    fixed_ln = 0
    for py_file in error_files:
        if fix_json_literal_newline(py_file):
            fixed_ln += 1
            print(f"✓ 修复\\n: {py_file.name}")

    # 然后修复双重括号
    fixed_bracket = 0
    import re
    for py_file in error_files:
        with open(py_file, 'r', encoding='utf-8') as f:
            content = f.read()
        original = content

        # 修复双重括号
        content = re.sub(r'(logger\.(info|error|warning|debug)\(\()json\.dumps\(', r'\1json\.dumps(', content)

        if content != original:
            with open(py_file, 'w', encoding='utf-8') as f:
                f.write(content)
            fixed_bracket += 1
            print(f"✓ 修复括号: {py_file.name}")

    # 验证
    remaining = 0
    for py_file in error_files:
        try:
            with open(py_file) as f:
                ast.parse(f.read())
        except:
            remaining += 1

    print(f"\n修复\\n: {fixed_ln} 个文件")
    print(f"修复括号: {fixed_bracket} 个文件")
    print(f"仍有错误: {remaining} 个文件")

    if remaining == 0:
        print("\n🎉 所有语法错误已修复！")


if __name__ == "__main__":
    main()
