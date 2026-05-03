#!/bin/bash
# 週報コメント自動生成 — cronから呼ばれるラッパースクリプト

SCRIPT_DIR="/Users/kawairyouhei/ナレッジ/scripts"
ENV_FILE="$SCRIPT_DIR/.env.weekly_report"
LOG_FILE="$SCRIPT_DIR/weekly_report.log"
PYTHON="/usr/bin/python3"

# 環境変数を読み込む
if [ -f "$ENV_FILE" ]; then
    export $(grep -v '^#' "$ENV_FILE" | grep -v '^$' | xargs)
else
    echo "❌ .env.weekly_report が見つかりません" >> "$LOG_FILE"
    exit 1
fi

# 実行日時を記録
echo "========================================" >> "$LOG_FILE"
echo "▶ 実行: $(date '+%Y-%m-%d %H:%M:%S JST')" >> "$LOG_FILE"

# Pythonスクリプトを実行（ログにも出力）
"$PYTHON" "$SCRIPT_DIR/weekly_report_processor.py" 2>&1 | tee -a "$LOG_FILE"

echo "▶ 終了: $(date '+%Y-%m-%d %H:%M:%S JST')" >> "$LOG_FILE"
