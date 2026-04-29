#!/usr/bin/env python3
"""
批量修复JSON语法错误 - 最终成功版
基于验证成功的方法批量修复
"""

from pathlib import Path


def fix_json_file(file_path: Path) -> bool:
    """修复单个文件"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        modified = False

        for i in range(len(lines)):
            original_line = lines[i]

            # 修复1: 字面量\n -> 真正的换行符
            if 'json.dumps({\\n' in original_line:
                lines[i] = original_line.replace('json.dumps({\\n', 'json.dumps({\n')
                modified = True
                print(f"  修复第{i+1}行: \\n -> 换行")

            # 修复2: 双重括号 (logger.xxx((json.dumps({ -> logger.xxx(json.dumps({)
            patterns = [
                ('logger.info((json.dumps({', 'logger.info(json.dumps({)'),
                ('logger.error((json.dumps({', 'logger.error(json.dumps({)'),
                ('logger.warning((json.dumps({', 'logger.warning(json.dumps({)'),
                ('logger.debug((json.dumps({', 'logger.debug(json.dumps({)')
            ]

            for pattern, replacement in patterns:
                if pattern in original_line:
                    lines[i] = original_line.replace(pattern, replacement)
                    modified = True
                    print(f"  修复第{i+1}行: 双重括号")

        if modified:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)
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

    print(f"发现 {len(error_files)} 个有语法错误的文件\n")

    # 逐个修复
    fixed_count = 0
    for py_file in error_files:
        print(f"处理: {py_file.name}")
        if fix_json_file(py_file):
            fixed_count += 1
            print(f"✓ 已修复\n")

    # 验证修复结果
    remaining_count = 0
    for py_file in error_files:
        try:
            with open(py_file) as f:
                ast.parse(f.read())
        except:
            remaining_count += 1
            print(f"✗ 仍有错误: {py_file.name}")

    print(f"\n{'='*60}")
    print(f"修复: {fixed_count} 个文件")
    print(f"仍有错误: {remaining_count} 个文件")
    print(f"{'='*60}")

    if remaining_count == 0:
        print("\n🎉🎉🎉 所有语法错误已修复！ 🎉🎉🎉")
    else:
        print(f"\n⚠️ 仍有 {remaining_count} 个文件需要进一步处理")


if __name__ == "__main__":
    main()
