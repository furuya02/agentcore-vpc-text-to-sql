import asyncio
import json
import os

import boto3
import psycopg2
from bedrock_agentcore.runtime import BedrockAgentCoreApp

app = BedrockAgentCoreApp()

MODEL_ID = "apac.anthropic.claude-sonnet-4-20250514-v1:0"

# DB 認証情報を Secrets Manager から取得（キャッシュ付き）
_db_config = None


def get_db_config():
    global _db_config
    if _db_config:
        return _db_config
    sm = boto3.client("secretsmanager", region_name="ap-northeast-1")
    secret = json.loads(
        sm.get_secret_value(SecretId=os.environ["DB_SECRET_ARN"])["SecretString"]
    )
    _db_config = {
        "host": secret["host"],
        "port": int(secret.get("port", 5432)),
        "dbname": os.environ.get("DB_NAME", "ecommerce"),
        "user": secret["username"],
        "password": secret["password"],
    }
    return _db_config


# ---- ツール ----

def tool_list_tables():
    conn = psycopg2.connect(**get_db_config())
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
    tables = {}
    for table, column, dtype in rows:
        tables.setdefault(table, []).append(f"  {column} ({dtype})")
    return "\n".join(f"{t}:\n" + "\n".join(cols) for t, cols in tables.items())


def tool_execute_query(sql):
    if not sql.strip().upper().startswith("SELECT"):
        return "エラー: SELECT文のみ実行可能です"
    conn = psycopg2.connect(**get_db_config())
    cur = conn.cursor()
    cur.execute(sql)
    columns = [d[0] for d in cur.description]
    rows = cur.fetchall()
    cur.close()
    conn.close()
    lines = [" | ".join(columns)]
    for row in rows:
        lines.append(" | ".join(str(v) for v in row))
    return "\n".join(lines)


TOOLS = {
    "list_tables": lambda inp: tool_list_tables(),
    "execute_query": lambda inp: tool_execute_query(inp.get("sql", "")),
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
                        "properties": {"sql": {"type": "string", "description": "実行するSQLクエリ"}},
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


# ---- エージェントループ ----

def run_agent(client, prompt):
    messages = [{"role": "user", "content": [{"text": prompt}]}]

    for _ in range(10):
        resp = client.converse(
            modelId=MODEL_ID,
            system=[{"text": SYSTEM_PROMPT}],
            messages=messages,
            inferenceConfig={"maxTokens": 2000},
            toolConfig=TOOL_CONFIG,
        )
        content = resp["output"]["message"]["content"]
        messages.append({"role": "assistant", "content": content})

        if resp["stopReason"] == "end_turn":
            return next((b["text"] for b in content if "text" in b), "")

        tool_results = []
        for block in content:
            if "toolUse" not in block:
                continue
            tu = block["toolUse"]
            result = TOOLS[tu["name"]](tu.get("input", {}))
            tool_results.append({
                "toolResult": {
                    "toolUseId": tu["toolUseId"],
                    "content": [{"text": result}],
                }
            })
        messages.append({"role": "user", "content": tool_results})

    return "エラー: 最大ターン数に達しました"


@app.entrypoint
async def invoke(payload, context):
    client = boto3.client("bedrock-runtime", region_name="ap-northeast-1")
    result = await asyncio.get_event_loop().run_in_executor(
        None, lambda: run_agent(client, payload.get("prompt", ""))
    )
    yield result


if __name__ == "__main__":
    app.run()
