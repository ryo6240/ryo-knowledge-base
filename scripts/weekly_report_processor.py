#!/usr/bin/env python3
"""
週報コメント自動生成スクリプト
=========================================
サロン生の個別チャンネルを巡回して週報を検出し、
りょうさんスタイルのコメント案を生成してりょうさんへ送付する。

使い方:
  python3 weekly_report_processor.py

環境変数（~/.zshrc に設定すること）:
  DISCORD_BOT_TOKEN   : Discordボットトークン
  ANTHROPIC_API_KEY   : Anthropic APIキー
"""

import json
import os
import re
import sys
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

import anthropic

# ======= 設定 =======
DISCORD_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# りょうさんへコメント案を送るDMチャンネル
RYO_DM_CHANNEL_ID = "1491442615336570950"

# ナレッジベースのルートパス
KNOWLEDGE_BASE = Path("/Users/kawairyouhei/ナレッジ")
SCRIPTS_DIR = KNOWLEDGE_BASE / "scripts"
CHANNEL_MAP_FILE = SCRIPTS_DIR / "channel_member_map.json"
STATE_FILE = SCRIPTS_DIR / "weekly_report_state.json"

# コメントスタイルガイドのパス
STYLE_GUIDE_PATH = Path(
    "/Users/kawairyouhei/.claude/projects/-Users-kawairyouhei-----/memory/feedback_weekly_comment_style.md"
)

# 週報と判定するキーワード（スコアリング用）
WEEKLY_REPORT_KEYWORDS = [
    "週報", "今週", "いいね", "マッチ", "デート", "電話", "LINE", "ライン",
    "達成", "目標", "結果", "振り返り", "件", "回", "人", "通", "枚",
]

# 週報と判定するスコアのしきい値
SCORE_THRESHOLD = 3
MIN_LENGTH = 80  # 最低文字数


# ======= 週報判定 =======

def score_weekly_report(text: str) -> int:
    """テキストが週報らしいかスコアを計算する（高いほど週報らしい）"""
    score = 0
    for kw in WEEKLY_REPORT_KEYWORDS:
        if kw in text:
            score += 1
    # 数字が2個以上含まれていると+1
    if len(re.findall(r'\d+', text)) >= 2:
        score += 1
    # 改行が3行以上あると+1（構造化されたテキスト）
    if text.count('\n') >= 3:
        score += 1
    return score


def is_weekly_report(text: str) -> bool:
    """テキストが週報かどうか判定する"""
    if len(text) < MIN_LENGTH:
        return False
    return score_weekly_report(text) >= SCORE_THRESHOLD


# ======= Discord API =======

def discord_headers() -> dict:
    return {
        "Authorization": f"Bot {DISCORD_TOKEN}",
        "Content-Type": "application/json",
    }


def fetch_recent_messages(channel_id: str, after_message_id: str = None, limit: int = 20) -> list:
    """Discordチャンネルから最新メッセージを取得する"""
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages?limit={limit}"
    if after_message_id:
        url += f"&after={after_message_id}"

    try:
        resp = requests.get(url, headers=discord_headers(), timeout=10)
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 403:
            # アクセス権がないチャンネルはスキップ
            return []
        else:
            print(f"  ⚠️  ch={channel_id} HTTP {resp.status_code}", file=sys.stderr)
            return []
    except Exception as e:
        print(f"  ⚠️  ch={channel_id} 取得エラー: {e}", file=sys.stderr)
        return []


def send_discord_message(channel_id: str, content: str) -> bool:
    """Discordチャンネルにメッセージを送信する"""
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    payload = {"content": content}
    try:
        resp = requests.post(url, headers=discord_headers(), json=payload, timeout=10)
        return resp.status_code in (200, 201)
    except Exception as e:
        print(f"  ⚠️  送信エラー ch={channel_id}: {e}", file=sys.stderr)
        return False


# ======= ナレッジ読み込み =======

def load_style_guide() -> str:
    """コメントスタイルガイドを読み込む"""
    if STYLE_GUIDE_PATH.exists():
        return STYLE_GUIDE_PATH.read_text(encoding="utf-8")
    return "（スタイルガイドが見つかりません）"


def load_member_profile(profile_path: str) -> str:
    """サロン生プロフィールを読み込む"""
    full_path = KNOWLEDGE_BASE / profile_path
    if full_path.exists():
        return full_path.read_text(encoding="utf-8")
    return "（プロフィールファイルが見つかりません）"


# ======= Claude API でコメント生成 =======

def generate_comment_draft(
    weekly_report: str,
    member_name: str,
    member_profile: str,
    style_guide: str,
) -> str:
    """Claude APIでりょうさんスタイルのコメント案を生成する"""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    system_prompt = f"""あなたは恋愛コンサルティングサービス「アップガイサロン」の運営を支援するAIアシスタントです。
りょうコーチ（オーナー）のスタイルで、サロン生の週報へのコメント案を生成します。

【コメントスタイルガイド】
{style_guide}

【サロン生プロフィール】
{member_profile}

以下のルールを必ず守ってください：
1. りょうコーチのスタイル（簡潔・ポジティブ・断言形式）に従う
2. 書き出しは活動のフェーズ名（初動・デート等）＋「お疲れ様です！」、フェーズが不明なら「お疲れ様です！」のみ
3. 未達・課題・改善点には触れず、達成できたことだけにフォーカス
4. 褒め方はシンプルに断言形式（「〜素晴らしいです」「〜成長ですね！」）
5. 来週のアドバイスは1〜2文で目的を一言で伝える形式
6. 締めは「引き続きファイトです！」
7. 全体で200〜400文字に収める（長すぎない）
"""

    user_prompt = f"""以下は{member_name}さんの週報です。りょうコーチスタイルのコメント案を1つ生成してください。

【週報内容】
{weekly_report}"""

    try:
        response = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=800,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        return f"（コメント生成エラー: {e}）"


# ======= りょうさんへ送付 =======

def format_ryo_message(
    member_name: str,
    member_channel_id: str,
    weekly_report: str,
    comment_draft: str,
) -> str:
    """りょうさんへ送るメッセージを整形する"""
    # 週報を500文字で省略
    report_preview = weekly_report[:500]
    if len(weekly_report) > 500:
        report_preview += "…（省略）"

    return f"""📝 **週報コメント案** — {member_name}さん

**【{member_name}さんの週報】**
{report_preview}

---

**【コメント案】**
{comment_draft}

---
📌 送信先: <#{member_channel_id}>
✅ OKなら「**送信OK {member_name}**」と返信してください"""


# ======= 状態管理 =======

def load_state() -> dict:
    """前回チェック時の最終メッセージIDを読み込む"""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_state(state: dict):
    """最終メッセージIDを保存する"""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ======= メイン処理 =======

def main():
    # 環境変数チェック
    if not DISCORD_TOKEN:
        print("❌ DISCORD_BOT_TOKEN が設定されていません。", file=sys.stderr)
        sys.exit(1)
    if not ANTHROPIC_API_KEY:
        print("❌ ANTHROPIC_API_KEY が設定されていません。", file=sys.stderr)
        sys.exit(1)

    print("🚀 週報コメント自動生成スクリプト開始")

    # チャンネルマップ読み込み
    with open(CHANNEL_MAP_FILE, "r", encoding="utf-8") as f:
        channel_map = json.load(f)

    # 前回状態・スタイルガイド読み込み
    state = load_state()
    style_guide = load_style_guide()

    found_count = 0
    checked_count = 0

    for channel_id, member_info in channel_map.items():
        member_name = member_info["name"]
        profile_path = member_info.get("profile_path", "")
        last_msg_id = state.get(channel_id)

        # チャンネルのメッセージを取得
        messages = fetch_recent_messages(channel_id, after_message_id=last_msg_id)
        checked_count += 1

        # 最新メッセージIDを更新
        if messages:
            # メッセージは新しい順なので先頭が最新
            state[channel_id] = messages[0]["id"]

        for msg in reversed(messages):  # 古い順に処理
            content = msg.get("content", "")
            msg_id = msg.get("id", "")

            # Botのメッセージはスキップ
            if msg.get("author", {}).get("bot", False):
                continue

            # 週報判定
            if not is_weekly_report(content):
                continue

            print(f"  📄 週報検出: {member_name}さん (ch={channel_id})")

            # プロフィール読み込み
            member_profile = load_member_profile(profile_path)

            # コメント案生成
            print(f"  🤖 コメント案を生成中...")
            comment_draft = generate_comment_draft(
                content, member_name, member_profile, style_guide
            )

            # りょうさんへ送付
            ryo_message = format_ryo_message(
                member_name, channel_id, content, comment_draft
            )
            success = send_discord_message(RYO_DM_CHANNEL_ID, ryo_message)
            if success:
                print(f"  ✅ りょうさんへ送付完了: {member_name}さん")
                found_count += 1
            else:
                print(f"  ❌ りょうさんへの送付失敗: {member_name}さん")

    # 状態を保存
    save_state(state)

    print(f"\n✅ 完了。チェックチャンネル数: {checked_count}、週報検出数: {found_count}")


if __name__ == "__main__":
    main()
