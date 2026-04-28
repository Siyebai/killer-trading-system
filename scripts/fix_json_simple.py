#!/usr/bin/env python3
"""
批量修复JSON语法错误 - 最简单直接版
使用简单的字符串替换，不依赖正则表达式
"""

from pathlib import Path


def fix_json_simple(file_path: Path) -> bool:
    """最简单的修复方法"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        modified = False

        for i in range(len(lines)):
            line = lines[i]

            # 修复1: logger.info((json.dumps({ -> logger.info(json.dumps({
            if 'logger.info((json.dumps({' in line:
                lines[i] = line.replace('logger.info((json.dumps({', 'logger.info(json.dumps({')
                modified = True
                print(f"  修复第{i+1}行: 双重括号")

            # 修复2: logger.error((json.dumps({ -> logger.error(json.dumps({
            if 'logger.error((json.dumps({' in line:
                lines[i] = line.replace('logger.error((json.dumps({', 'logger.error(json.dumps({')
                modified = True
                print(f"  修复第{i+1}行: 双重括号")

            # 修复3: logger.warning((json.dumps({ -> logger.warning(json.dumps({
            if 'logger.warning((json.dumps({' in line:
                lines[i] = line.replace('logger.warning((json.dumps({', 'logger.warning(json.dumps({')
                modified = True
                print(f"  修复第{i+1}行: 双重括号")

            # 修复4: logger.debug((json.dumps({ -> logger.debug(json.dumps({
            if 'logger.debug((json.dumps({' in line:
                lines[i] = line.replace('logger.debug((json.dumps({', 'logger.debug(json.dumps({')
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

    fixed = 0
    for py_file in error_files:
        if fix_json_simple(py_file):
            fixed += 1
            print(f"✓ 修复: {py_file.name}")

    # 验证
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
    else:
        print(f"\n⚠️ 仍有 {remaining} 个文件需要手动修复")


if __name__ == "__main__":
    main()
