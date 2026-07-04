#!/usr/bin/env bash
# 小爪 dev 启动包装:注入 PATH + 免更新提示,常驻运行
set -euo pipefail
export PATH="$HOME/.npm-global/bin:$PATH"
export LARKSUITE_CLI_NO_UPDATE_NOTIFIER=1
cd "$HOME/lark-agent"
exec python3 agent.py --minutes 0
