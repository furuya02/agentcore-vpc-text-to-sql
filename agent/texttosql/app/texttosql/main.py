import asyncio, json, os
import boto3, psycopg2
from bedrock_agentcore.runtime import BedrockAgentCoreApp

app = BedrockAgentCoreApp()
MODEL_ID = "apac.anthropic.claude-sonnet-4-20250514-v1:0"
_db = None

def db_config():
    global _db
    if _db: return _db
    s = json.loads(boto3.client("secretsmanager", region_name="ap-northeast-1")
                   .get_secret_value(SecretId=os.environ["DB_SECRET_ARN"])["SecretString"])
    _db = dict(host=s["host"], port=int(s.get("port", 5432)),
               dbname=os.environ.get("DB_NAME", "ecommerce"),
               user=s["username"], password=s["password"])
    return _db

def list_tables(_):
    conn = psycopg2.connect(**db_config())
    cur = conn.cursor()
    cur.execute("SELECT table_name, column_name, data_type FROM information_schema.columns "
                "WHERE table_schema='public' ORDER BY table_name, ordinal_position")
    rows = cur.fetchall(); cur.close(); conn.close()
    t = {}
    for tbl, col, typ in rows:
        t.setdefault(tbl, []).append(f"  {col} ({typ})")
    return "\n".join(f"{k}:\n" + "\n".join(v) for k, v in t.items())

def execute_query(inp):
    sql = inp.get("sql", "")
    if not sql.strip().upper().startswith("SELECT"):
        return "エラー: SELECT文のみ実行可能です"
    conn = psycopg2.connect(**db_config())
    cur = conn.cursor()
    cur.execute(sql)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall(); cur.close(); conn.close()
    return "\n".join([" | ".join(cols)] + [" | ".join(str(v) for v in r) for r in rows])

TOOLS = {"list_tables": list_tables, "execute_query": execute_query}

TOOL_CONFIG = {"tools": [
    {"toolSpec": {"name": "list_tables",
                  "description": "データベースのテーブル一覧とカラム情報を取得します",
                  "inputSchema": {"json": {"type": "object", "properties": {}}}}},
    {"toolSpec": {"name": "execute_query",
                  "description": "SQLクエリを実行して結果を返します。SELECT文のみ実行可能です。",
                  "inputSchema": {"json": {"type": "object",
                      "properties": {"sql": {"type": "string", "description": "実行するSQLクエリ"}},
                      "required": ["sql"]}}}},
]}

SYSTEM = ("あなたはECサイトの注文データベースに問い合わせるText-to-SQLアシスタントです。\n"
          "手順: 1.list_tablesでテーブル構造確認 2.SQL生成 3.execute_queryで実行 4.日本語で回答\n"
          "注意: SELECT文のみ実行可能。日本語で回答すること。")

def run(client, prompt):
    msgs = [{"role": "user", "content": [{"text": prompt}]}]
    for _ in range(10):
        r = client.converse(modelId=MODEL_ID, system=[{"text": SYSTEM}],
                            messages=msgs, inferenceConfig={"maxTokens": 2000}, toolConfig=TOOL_CONFIG)
        c = r["output"]["message"]["content"]
        msgs.append({"role": "assistant", "content": c})
        if r["stopReason"] == "end_turn":
            return next((b["text"] for b in c if "text" in b), "")
        msgs.append({"role": "user", "content": [
            {"toolResult": {"toolUseId": b["toolUse"]["toolUseId"],
                            "content": [{"text": TOOLS[b["toolUse"]["name"]](b["toolUse"].get("input", {}))}]}}
            for b in c if "toolUse" in b]})
    return ""

@app.entrypoint
async def invoke(payload, context):
    client = boto3.client("bedrock-runtime", region_name="ap-northeast-1")
    yield await asyncio.get_event_loop().run_in_executor(
        None, lambda: run(client, payload.get("prompt", "")))

if __name__ == "__main__":
    app.run()
