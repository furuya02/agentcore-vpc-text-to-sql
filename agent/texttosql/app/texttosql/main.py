import asyncio
import json
import os

import boto3
import psycopg2
from bedrock_agentcore.runtime import BedrockAgentCoreApp

app = BedrockAgentCoreApp()
log = app.logger

MODEL_ID = "apac.anthropic.claude-sonnet-4-20250514-v1:0"

# DB 認証情報を Secrets Manager から取得（キャッシュ付き）
_db_config: dict | None = None


def get_db_config() -> dict:
    global _db_config
    if _db_config is not None:
        return _db_config

    sm = boto3.client("secretsmanager", region_name="ap-northeast-1")
    secret_arn = os.environ["DB_SECRET_ARN"]
    resp = sm.get_secret_value(SecretId=secret_arn)
    secret = json.loads(resp["SecretString"])

    _db_config = {
        "host": secret["host"],
        "port": int(secret.get("port", 5432)),
        "dbname": os.environ.get("DB_NAME", "ecommerce"),
        "user": secret["username"],
        "password": secret["password"],
        "connect_timeout": 30,
    }
    return _db_config


def get_connection() -> psycopg2.extensions.connection:
    return psycopg2.connect(**get_db_config())


# ---- Tool 実装 ----

def tool_list_tables() -> str:
    """データベースのテーブル一覧とカラム情報を取得"""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT table_name, column_name, data_type "
        "FROM information_schema.columns "
        "WHERE table_schema = 'public' "
        "ORDER BY table_name, ordinal_position"
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    tables: dict[str, list[str]] = {}
    for table, column, dtype in rows:
        tables.setdefault(table, []).append(f"  {column} ({dtype})")

    return "\n".join(f"{t}:\n" + "\n".join(cols) for t, cols in tables.items())


def tool_execute_query(sql: str) -> str:
    """SQLクエリを実行して結果を返す。SELECT文のみ。"""
    if not sql.strip().upper().startswith("SELECT"):
        return "エラー: SELECT文のみ実行可能です"

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(sql)
        columns = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    lines = [" | ".join(columns)]
    for row in rows:
        lines.append(" | ".join(str(v) for v in row))
    return "\n".join(lines)


TOOL_DISPATCH = {
    "list_tables": lambda _input: tool_list_tables(),
    "execute_query": lambda _input: tool_execute_query(_input.get("sql", "")),
}

TOOL_CONFIG = {
    "tools": [
        {
            "toolSpec": {
                "name": "list_tables",
                "description": "データベースのテーブル一覧とカラム情報を取得します",
                "inputSchema": {"json": {"type": "object", "properties": {}}},
            }
        },
        {
            "toolSpec": {
                "name": "execute_query",
                "description": "SQLクエリを実行して結果を返します。SELECT文のみ実行可能です。",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "sql": {
                                "type": "string",
                                "description": "実行するSQLクエリ",
                            }
                        },
                        "required": ["sql"],
                    }
                },
            }
        },
    ]
}

SYSTEM_PROMPT = """\
あなたはECサイトの注文データベースに問い合わせるText-to-SQLアシスタントです。

手順:
1. まず list_tables でテーブル構造を確認
2. ユーザーの質問に対応するSQLを生成
3. execute_query で実行
4. 結果を日本語で分かりやすく回答

注意:
- SELECT文のみ実行可能
- 日本語で回答すること
"""

MAX_TURNS = 10


def run_agent(client: object, prompt: str) -> str:
    """boto3 converse API で直接 tool loop を実行."""
    messages: list[dict] = [
        {"role": "user", "content": [{"text": prompt}]},
    ]

    for turn in range(MAX_TURNS):
        log.info(f"[Agent] Turn {turn + 1}: calling converse...")
        response = client.converse(
            modelId=MODEL_ID,
            system=[{"text": SYSTEM_PROMPT}],
            messages=messages,
            inferenceConfig={"maxTokens": 2000},
            toolConfig=TOOL_CONFIG,
        )

        stop_reason = response["stopReason"]
        assistant_content = response["output"]["message"]["content"]
        messages.append({"role": "assistant", "content": assistant_content})
        log.info(f"[Agent] Turn {turn + 1}: stop_reason={stop_reason}")

        if stop_reason == "end_turn":
            # 最終応答テキストを取得
            for block in assistant_content:
                if "text" in block:
                    return block["text"]
            return ""

        if stop_reason == "tool_use":
            tool_results: list[dict] = []
            for block in assistant_content:
                if "toolUse" not in block:
                    continue
                tool_use = block["toolUse"]
                tool_name = tool_use["name"]
                tool_input = tool_use.get("input", {})
                tool_use_id = tool_use["toolUseId"]

                log.info(f"[Agent] Executing tool: {tool_name}")
                handler = TOOL_DISPATCH.get(tool_name)
                if handler:
                    try:
                        result_text = handler(tool_input)
                    except Exception as e:
                        result_text = f"エラー: {e}"
                else:
                    result_text = f"エラー: 不明なツール {tool_name}"

                log.info(f"[Agent] Tool {tool_name} result: {result_text[:200]}")
                tool_results.append(
                    {
                        "toolResult": {
                            "toolUseId": tool_use_id,
                            "content": [{"text": result_text}],
                        }
                    }
                )

            messages.append({"role": "user", "content": tool_results})
        else:
            return f"予期しない stop_reason: {stop_reason}"

    return "エラー: 最大ターン数に達しました"


@app.entrypoint
async def invoke(payload: dict, context: object) -> None:
    log.info("Invoking Text-to-SQL Agent...")

    client = boto3.client("bedrock-runtime", region_name="ap-northeast-1")
    prompt = payload.get("prompt", "")
    log.info(f"Prompt: {prompt[:200]}")

    result = await asyncio.get_event_loop().run_in_executor(
        None, lambda: run_agent(client, prompt)
    )

    log.info(f"Agent completed. Result: {result[:200]}")
    yield result


if __name__ == "__main__":
    app.run()
