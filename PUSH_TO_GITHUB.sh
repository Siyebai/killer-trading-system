#!/bin/bash
# 白夜交易系统 - GitHub推送脚本

echo "======================================"
echo "白夜交易系统 - GitHub推送"
echo "======================================"
echo ""
echo "步骤1: 确认Git配置"
git config user.email "你的邮箱@example.com"
git config user.name "你的名字"
echo ""

echo "步骤2: 提交所有更改"
git add -A
git commit -m "v1.4 白夜交易系统发布

策略: MomReversal v1.4, WR=62.6%, 4品种并行
风控: 固定3U/笔, 日熔断15U, 月熔断45U
文档: README+策略说明+部署指南
回测: BTC 180天 WR=62.6% 月收益+25.8U"
echo ""

echo "步骤3: 推送到GitHub"
echo "请选择方式:"
echo "1) HTTPS (需要输入Token)"
echo "2) SSH (需提前配置SSH Key)"
echo ""
read -p "选择 [1/2]: " choice

if [ "$choice" = "1" ]; then
    git push origin main
elif [ "$choice" = "2" ]; then
    git remote set-url origin git@github.com:Siyebai/killer-trading-system.git
    git push origin main
else
    echo "无效选择"
    exit 1
fi

echo ""
echo "✅ 推送完成!"
echo "仓库地址: https://github.com/Siyebai/killer-trading-system"
