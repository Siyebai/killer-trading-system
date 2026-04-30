#!/bin/bash
# GitHub Push Script for Killer Trading System
# Usage: ./push_to_github.sh <GITHUB_TOKEN>
# 
# Steps to get a GitHub Token:
# 1. Visit: https://github.com/settings/tokens/new
# 2. Create Classic PAT, check: repo (全部), gist
# 3. Copy the token and run: ./push_to_github.sh YOUR_TOKEN_HERE

TOKEN="$1"
if [ -z "$TOKEN" ]; then
    echo "Usage: $0 <GITHUB_TOKEN>"
    echo ""
    echo "To get a GitHub token:"
    echo "  1. Visit: https://github.com/settings/tokens/new"
    echo "  2. Create Classic PAT with scopes: repo, gist"
    echo "  3. Copy the token and pass it as argument"
    exit 1
fi

cd /workspace/projects/trading-simulator

# Update remote with new token
git remote set-url origin "https://${TOKEN}@github.com/Siyebai/killer-trading-system.git"

# Push all branches
echo "Pushing to GitHub..."
git push origin complete-system main --force 2>&1

# Restore remote URL (don't store token)
git remote set-url origin "https://github.com/Siyebai/killer-trading-system.git"
echo "Done! Remote URL restored to public access."
