import json
import os

import boto3
import psycopg2
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from model.load import load_model
from strands import Agent, tool

app = BedrockAgentCoreApp()

# DB 認証情報を Secrets Manager から取得
_db_config: dict | None = None


def get_db_config() -> dict:
    global _db_config
    if _db_config is not None:
        return _db_config

    secret_arn = os.environ["DB_SECRET_ARN"]
    region = os.environ.get("AWS_REGION", "ap-northeast-1")

    client = boto3.client("secretsmanager", region_name=region)
    secret = json.loads(client.get_secret_value(SecretId=secret_arn)["SecretString"])

    _db_config = {
        "host": secret["host"],
        "port": int(secret.get("port", 5432)),
        "dbname": os.environ.get("DB_NAME", "ecommerce"),
        "user": secret["username"],
        "password": secret["password"],
    }
    return _db_config


def get_connection() -> psycopg2.extensions.connection:
    return psycopg2.connect(**get_db_config())


@tool
def list_tables() -> str:
    """データベースのテーブル一覧とカラム情報を取得します"""
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


@tool
def execute_query(sql: str) -> str:
    """SQLクエリを実行して結果を返します。SELECT文のみ実行可能です。"""
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


@app.entrypoint
async def invoke(payload: dict, context: object) -> None:
    agent = Agent(
        model=load_model(),
        system_prompt=SYSTEM_PROMPT,
        tools=[list_tables, execute_query],
    )

    stream = agent.stream_async(payload.get("prompt", ""))
    async for event in stream:
        if "data" in event and isinstance(event["data"], str):
            yield event["data"]


if __name__ == "__main__":
    app.run()
