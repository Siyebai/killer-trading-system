# -*- coding: utf-8 -*-
"""
测试套件初始化
"""
import sys
import os

# 确保scripts/在路径中
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _project_root)
