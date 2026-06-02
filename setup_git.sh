#!/usr/bin/env bash
# AgentOps — one-time GitHub setup script
# Run this from Git Bash: bash setup_git.sh

set -e

# ── Fill these in ─────────────────────────────────────────
GITHUB_TOKEN="PASTE_YOUR_TOKEN_HERE"
GITHUB_USERNAME="PASTE_YOUR_USERNAME_HERE"
REPO_NAME="agentops"
# ─────────────────────────────────────────────────────────

echo "==> Creating GitHub repo '$REPO_NAME'..."
curl -s -X POST \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"$REPO_NAME\",\"description\":\"Phase 1 agent governance platform — lifecycle, maker-checker, eval-gated promotion, audit log\",\"private\":false}" \
  https://api.github.com/user/repos | python3 -c "import sys,json; r=json.load(sys.stdin); print('Repo URL:', r.get('html_url', r.get('message','error')))"

echo ""
echo "==> Initializing git..."
git init
git config user.name "Krishna Paruchuri"
git config user.email "krishna1parchuri@gmail.com"

git add .
git commit -m "feat: AgentOps Phase 1 — agent governance platform

- Registry with lifecycle state machine (7 stages)
- Maker-checker approval workflow
- Eval-gated promotion (threshold enforced at API level)
- Cost tracking (per-agent daily rollup)
- Retirement workflow
- Immutable audit log (INSERT-only)
- SOP Deviation Review seeded with live eval/cost data
- Single-file React SPA: Registry / Agent Detail / Governance Queue"

echo ""
echo "==> Setting remote and pushing..."
git remote add origin "https://${GITHUB_USERNAME}:${GITHUB_TOKEN}@github.com/${GITHUB_USERNAME}/${REPO_NAME}.git"
git branch -M main
git push -u origin main

echo ""
echo "Done! Repo live at: https://github.com/${GITHUB_USERNAME}/${REPO_NAME}"
