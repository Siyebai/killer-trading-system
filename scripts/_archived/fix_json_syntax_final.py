#!/usr/bin/env python3
"""
批量修复JSON语法错误 - 最终精确版
修复所有已知的JSON语法错误模式
"""

from pathlib import Path
import re


def fix_json_syntax_errors(file_path: Path) -> bool:
    """修复JSON语法错误"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        original = content

        # 修复模式1: logger.info((json.dumps({ -> logger.info(json.dumps({
        # 双重左括号错误
        pattern1 = r'logger\.(info|error|warning|debug)\(\(json\.dumps\(\{'
        replacement1 = r'logger.\1(json.dumps({'
        content = re.sub(pattern1, replacement1, content)

        # 修复模式2: }), -> }),
        # 在json.dumps块末尾，移除多余的逗号
        pattern2 = r'json\.dumps\(\{[^}]+\},\)\)'
        replacement2 = r'json.dumps({\1})'
        content = re.sub(pattern2, replacement2, content)

        # 修复模式3: 处理跨行的}),}模式
        lines = content.split('\n')
        for i in range(len(lines) - 1):
            # 当前行以}),结尾，下一行以}开头
            if lines[i].rstrip().endswith('}),') and lines[i + 1].strip().startswith('}'):
                lines[i] = lines[i].rstrip()[:-1]  # 移除逗号
                # 添加右括号和逗号
                lines[i] += '),'
                # 下一行添加右括号
                lines[i + 1] = '})' + lines[i + 1]

        content = '\n'.join(lines)

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

    # 找出有错误的文件
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

    # 逐个修复
    fixed = 0
    for py_file in error_files:
        if fix_json_syntax_errors(py_file):
            fixed += 1
            print(f"✓ 修复: {py_file.name}")

    # 验证修复结果
    remaining = 0
    for py_file in error_files:
        try:
            with open(py_file) as f:
                ast.parse(f.read())
        except:
            remaining += 1

    print(f"\n修复: {fixed} 个文件")
    print(f"仍有错误: {remaining} 个文件")

    if remaining == 0:
        print("\n🎉 所有语法错误已修复！")


if __name__ == "__main__":
    main()
