#!/usr/bin/env python3
"""
Claude Code セッション終了時に自動でデイリーメモを保存するスクリプト。
Stop フックとして ~/.claude/settings.json に登録して使用する。
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ======= 設定 =======
MEMO_DIR = Path("/Users/kawairyouhei/ナレッジ/Claudeデイリーメモ")
PROJECTS_DIR = Path.home() / ".claude" / "projects"
JST = timezone(timedelta(hours=9))
TODAY = datetime.now(JST).strftime("%Y-%m-%d")
# ====================


def extract_messages(jsonl_path: Path) -> list[dict]:
    """JSONLファイルからユーザー・アシスタントのメッセージを抽出する。"""
    messages = []
    seen_assistant_ids = set()

    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            entry_type = entry.get("type")
            msg = entry.get("message", {})

            if entry_type == "user":
                content = msg.get("content", "")
                if isinstance(content, str) and content.strip():
                    messages.append({"role": "user", "text": content.strip()})
                elif isinstance(content, list):
                    texts = [
                        c.get("text", "")
                        for c in content
                        if c.get("type") == "text"
                    ]
                    combined = "\n".join(t for t in texts if t.strip())
                    if combined:
                        messages.append({"role": "user", "text": combined})

            elif entry_type == "assistant":
                msg_id = msg.get("id", "")
                if msg_id and msg_id in seen_assistant_ids:
                    continue
                if msg_id:
                    seen_assistant_ids.add(msg_id)

                content = msg.get("content", [])
                if isinstance(content, list):
                    texts = [
                        c.get("text", "")
                        for c in content
                        if c.get("type") == "text"
                    ]
                    combined = "\n".join(t for t in texts if t.strip())
                    if combined:
                        messages.append({"role": "assistant", "text": combined})

    return messages


def find_today_sessions() -> list[Path]:
    """今日更新されたJSONLセッションファイルを返す。"""
    today_files = []
    for jsonl in PROJECTS_DIR.rglob("*.jsonl"):
        try:
            mtime = datetime.fromtimestamp(jsonl.stat().st_mtime, tz=JST)
            if mtime.strftime("%Y-%m-%d") == TODAY:
                today_files.append(jsonl)
        except OSError:
            continue
    return sorted(today_files, key=lambda p: p.stat().st_mtime)


def build_transcript_text(messages: list[dict]) -> str:
    """メッセージリストを読みやすいテキストに変換する。"""
    lines = []
    for m in messages:
        prefix = "【りょう】" if m["role"] == "user" else "【Claude】"
        lines.append(f"{prefix}\n{m['text']}\n")
    return "\n---\n".join(lines)


def generate_summary(transcript: str, api_key: str) -> str:
    """Anthropic APIを使って会話サマリーを生成する。"""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[
            {
                "role": "user",
                "content": f"""以下はClaude Codeとのやりとりです。
恋愛コーチ「りょう」の視点から、今日の気づき・学び・意思決定のポイントをまとめてください。

出力形式：
## 今日の気づきサマリー
### 主なトピック
- （箇条書きで3〜5個）

### りょうの意思決定・行動
- （今日どんな判断をし、何を実装・整備しようとしたか）

### 明日へのヒント
- （次のアクションや引き続き考えるべき点）

---
【会話ログ】
{transcript[:6000]}
""",
            }
        ],
    )
    return response.content[0].text


def save_memo(summary: str, transcript: str):
    """デイリーメモをMarkdownファイルとして保存する。"""
    MEMO_DIR.mkdir(parents=True, exist_ok=True)
    output_path = MEMO_DIR / f"{TODAY}.md"

    now_str = datetime.now(JST).strftime("%Y-%m-%d %H:%M")

    # 既存ファイルがあれば追記、なければ新規作成
    if output_path.exists():
        existing = output_path.read_text(encoding="utf-8")
        content = existing + f"\n\n---\n\n## セッション追記 ({now_str})\n\n{summary}\n\n<details>\n<summary>会話ログ全文</summary>\n\n{transcript}\n\n</details>\n"
    else:
        content = f"""# Claudeデイリーメモ {TODAY}

> 自動生成: Claude Code Stopフック
> 最終更新: {now_str}

{summary}

---

<details>
<summary>会話ログ全文</summary>

{transcript}

</details>
"""

    output_path.write_text(content, encoding="utf-8")
    print(f"[daily-memo] 保存完了: {output_path}", file=sys.stderr)


def load_api_key() -> str:
    """ANTHROPIC_API_KEY を環境変数 → ~/.claude/.env の順で探す。"""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key
    env_path = Path.home() / ".claude" / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("ANTHROPIC_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def main():
    api_key = load_api_key()

    # 今日のセッションファイルを探す
    session_files = find_today_sessions()
    if not session_files:
        print("[daily-memo] 今日のセッションファイルが見つかりません", file=sys.stderr)
        return

    # すべての今日のセッションからメッセージを集約
    all_messages = []
    for sf in session_files:
        all_messages.extend(extract_messages(sf))

    if not all_messages:
        print("[daily-memo] メッセージが見つかりません", file=sys.stderr)
        return

    transcript = build_transcript_text(all_messages)

    if api_key:
        try:
            summary = generate_summary(transcript, api_key)
        except Exception as e:
            print(f"[daily-memo] API呼び出しエラー: {e}", file=sys.stderr)
            summary = "（サマリー生成失敗 — ログのみ保存）"
    else:
        summary = "（ANTHROPIC_API_KEY 未設定 — ログのみ保存）"

    save_memo(summary, transcript)


if __name__ == "__main__":
    main()
