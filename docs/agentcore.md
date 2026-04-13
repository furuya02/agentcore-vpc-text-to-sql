# AgentCore 解説

## 1. Amazon Bedrock AgentCore とは

Amazon Bedrock AgentCore は、AI エージェントをスケーラブルにデプロイ・実行するためのマネージドランタイムサービスです。開発者はエージェントのコードに集中し、インフラ管理（コンテナ、スケーリング、ルーティング等）は AgentCore が担当します。

### 主な特徴

| 特徴 | 説明 |
|:-----|:-----|
| **マネージドランタイム** | コンテナイメージの構築・管理が不要。Python コードを直接デプロイ（`CodeZip`） |
| **自動スケーリング** | リクエスト量に応じてセッション数を自動調整 |
| **VPC 対応** | VPC 内のプライベートリソース（RDS、ElastiCache 等）にアクセス可能 |
| **フレームワーク非依存** | Strands Agents、LangChain、独自フレームワーク等を自由に選択可能 |
| **ストリーミング応答** | `yield` / `async for` によるレスポンスストリーミングをネイティブサポート |

### AgentCore のコンポーネント

```
agentcore CLI (v0.8.0)
  ├── create    … プロジェクトの雛形を生成（--network-mode VPC 対応）
  ├── deploy    … コードをビルド・デプロイ（CDK マネージド）
  ├── configure … 設定の変更（VPC、環境変数等）
  ├── invoke    … エージェントの呼び出し
  ├── status    … エンドポイントの状態確認
  └── destroy   … エージェントの削除
```

---

## 2. このプロジェクトでの AgentCore 構成

### 2.1 構成ファイル（`agentcore/agentcore.json`）

本プロジェクトの AgentCore は以下のように構成されています（agentcore CLI v0.8.0 の JSON 形式）。

```json
{
  "$schema": "https://schema.agentcore.aws.dev/v1/agentcore.json",
  "name": "texttosql",
  "version": 1,
  "managedBy": "CDK",
  "runtimes": [
    {
      "name": "texttosql",
      "build": "CodeZip",
      "entrypoint": "main.py",
      "codeLocation": "app/texttosql/",
      "runtimeVersion": "PYTHON_3_13",
      "networkMode": "VPC",
      "networkConfig": {
        "subnets": ["subnet-..."],
        "securityGroups": ["sg-..."]
      },
      "protocol": "HTTP",
      "envVars": [
        { "name": "DB_SECRET_ARN", "value": "arn:aws:secretsmanager:..." },
        { "name": "DB_NAME", "value": "ecommerce" }
      ]
    }
  ]
}
```

**重要な設定値:**

| 設定 | 値 | 説明 |
|:-----|:---|:-----|
| `managedBy` | `CDK` | CDK マネージドアプローチでデプロイ |
| `build` | `CodeZip` | ソースコードを ZIP でアップロードしてデプロイ（Docker ファイル不要） |
| `runtimeVersion` | `PYTHON_3_13` | Python 3.13 ランタイム |
| `agent_id` | `texttosql_texttosql-m1BnYvBet3` | AgentCore が自動生成したエージェント ID |
| `protocol` | `HTTP` | サーバープロトコル |
| `envVars` | `DB_SECRET_ARN`, `DB_NAME` | 環境変数は agentcore.json 内で定義 |

### 2.2 エージェントコード

エントリポイントは `agent/texttosql/app/texttosql/main.py` です。

> **注意:** 当初は Strands Agents SDK（`Agent.stream_async`）を使用していましたが、VPC モード内で応答がハングする問題が発生したため、boto3 の `converse` API を直接呼び出す方式に変更しました（詳細はセクション 7 を参照）。

```python
app = BedrockAgentCoreApp()

@app.entrypoint
async def invoke(payload: dict, context: object) -> None:
    client = boto3.client("bedrock-runtime", region_name="ap-northeast-1")
    prompt = payload.get("prompt", "")
    result = await asyncio.get_event_loop().run_in_executor(
        None, lambda: run_agent(client, prompt)
    )
    yield result
```

`run_agent` 関数は boto3 の `client.converse()` を呼び出し、tool_use / tool_result のループを回します。

```python
def run_agent(client: object, prompt: str) -> str:
    messages = [{"role": "user", "content": [{"text": prompt}]}]
    for turn in range(MAX_TURNS):
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

        if stop_reason == "end_turn":
            # 最終応答テキストを返す
            ...
        if stop_reason == "tool_use":
            # ツール実行 → tool_result を messages に追加 → 再度 converse
            ...
```

**処理フロー:**

1. `BedrockAgentCoreApp` がリクエストを受信
2. `payload` から `prompt` を取得
3. boto3 `converse` API で Bedrock (Claude Sonnet 4) を呼び出し、tool loop を実行:
   - `list_tables` ツール: Aurora からテーブル構造を取得
   - `execute_query` ツール: 生成した SQL を Aurora で実行（SELECT のみ）
   - `stop_reason` が `end_turn` になるまでループ
4. 結果を自然言語で返却

### 2.3 依存パッケージ

```toml
dependencies = [
    "bedrock-agentcore >= 1.0.3",     # AgentCore SDK（strands-agents を推移的に含む）
    "psycopg2-binary >= 2.9.0",       # PostgreSQL ドライバ
    "boto3 >= 1.35.0",                # AWS SDK（Bedrock converse API / Secrets Manager 用）
]
```

> **補足:** `bedrock-agentcore` の依存関係として `strands-agents` が推移的にインストールされますが、本プロジェクトのコードでは Strands SDK を直接使用していません。boto3 の `converse` API を直接呼び出しています。

### 2.4 LLM モデル設定

```python
# agent/texttosql/app/texttosql/main.py
MODEL_ID = "apac.anthropic.claude-sonnet-4-20250514-v1:0"
```

MODEL_ID は `main.py` 内で直接定義しています（別ファイル `model/load.py` は廃止）。

`ap-northeast-1` では Bedrock のオンデマンド呼び出しが使えないモデルがあるため、**APAC Inference Profile ID** を使用しています。

| パターン | 動作 |
|:---------|:-----|
| `apac.anthropic.claude-sonnet-4-...` | OK — APAC Inference Profile 経由 |
| `anthropic.claude-sonnet-4-...` | NG — on-demand 非対応エラー |
| `us.anthropic.claude-sonnet-4-...` | NG — リージョン不一致 |

---

## 3. VPC モード詳細

AgentCore の VPC モードは、このプロジェクトの**核心部分**です。通常の AgentCore は PUBLIC モード（インターネットアクセス可能）で動作しますが、本プロジェクトでは VPC 内のプライベートリソース（Aurora）にアクセスするため、VPC モードを使用しています。

### 3.1 PUBLIC モード vs VPC モード

```
【PUBLIC モード（デフォルト）】
┌─────────────────────────────────┐
│  AgentCore Runtime              │
│  (AWS マネージド環境)             │
│                                 │
│  → インターネットアクセス可能      │
│  → VPC 内リソースにはアクセス不可  │
└─────────────────────────────────┘

【VPC モード（本プロジェクト）】
┌─────────────────────────────────────────┐
│  VPC (10.0.0.0/16)                       │
│  ┌───────────────────────────────────┐   │
│  │  Private Subnet                   │   │
│  │  ┌─────────────┐  ┌───────────┐   │   │
│  │  │ AgentCore   │──│  Aurora    │   │   │
│  │  │ Runtime     │  │  (RDS)    │   │   │
│  │  └──────┬──────┘  └───────────┘   │   │
│  │         │                         │   │
│  │  ┌──────┴──────────────────────┐  │   │
│  │  │ VPC Endpoints               │  │   │
│  │  │ (Bedrock, Logs, Secrets)    │  │   │
│  │  └─────────────────────────────┘  │   │
│  └───────────────────────────────────┘   │
└─────────────────────────────────────────┘
```

### 3.2 VPC モードの設定方法

`agentcore/agentcore.json` の `networkMode` / `networkConfig` セクションで指定します。

```json
{
  "runtimes": [
    {
      "networkMode": "VPC",
      "networkConfig": {
        "subnets": [
          "subnet-059414501ee87baa2",
          "subnet-0d95b29308468e6c7"
        ],
        "securityGroups": [
          "sg-0dfaf32456547f9df"
        ]
      }
    }
  ]
}
```

> **注意:** agentcore CLI v0.8 では、`agentcore create --network-mode VPC --subnets subnet-xxx,subnet-yyy --security-groups sg-xxx` のようにプロジェクト作成時に VPC モードを指定できます。agentcore.json を直接編集しても同様の効果があります。

### 3.3 VPC 設計

本プロジェクトの VPC は CDK (`cdk/lib/text-to-sql-stack.ts`) で構築されています。

#### サブネット構成

```typescript
const vpc = new ec2.Vpc(this, 'Vpc', {
  maxAzs: 2,
  natGateways: 0,                        // NAT Gateway なし（コスト削減）
  subnetConfiguration: [
    {
      name: 'Private',
      subnetType: ec2.SubnetType.PRIVATE_ISOLATED,  // 完全にプライベート
      cidrMask: 24,
    },
  ],
});
```

| 項目 | 設定 | 理由 |
|:-----|:-----|:-----|
| **サブネットタイプ** | `PRIVATE_ISOLATED` | インターネットへのルートなし。最高のセキュリティ |
| **AZ 数** | 2（Multi-AZ） | Aurora の Multi-AZ 要件を満たすため |
| **NAT Gateway** | なし（0） | コスト削減。外部通信は VPC Endpoint 経由 |
| **CIDR** | 10.0.0.0/16（各サブネット /24） | 検証用途に十分なアドレス空間 |

#### なぜ PRIVATE_ISOLATED を選んだのか

| サブネットタイプ | インターネット | NAT Gateway | コスト |
|:----------------|:-------------|:-----------|:------|
| `PUBLIC` | あり | 不要 | 低 |
| `PRIVATE_WITH_EGRESS` | NAT 経由 | 必要 | **高**（~$45/月 per NAT GW） |
| `PRIVATE_ISOLATED` | なし | 不要 | **最低** |

本プロジェクトではインターネットアクセスが不要（Bedrock、Logs、Secrets Manager は VPC Endpoint で代替）のため、最もコストの低い `PRIVATE_ISOLATED` を採用しています。

### 3.4 Security Group 設計

```
┌──────────────┐                     ┌──────────────┐
│ AgentCore SG │ ─── TCP 5432 ───→  │  Aurora SG   │
│              │                     │              │
│ Outbound:    │                     │ Inbound:     │
│  All allowed │                     │  5432 from   │
│              │                     │  AgentCore   │
│              │                     │  SG のみ     │
└──────────────┘                     └──────────────┘
```

**AgentCore SG（`agentCoreSg`）:**
- Outbound: 全許可（`allowAllOutbound: true`）
- VPC Endpoint、Aurora への通信を許可

**Aurora SG（`auroraSg`）:**
- Outbound: 全拒否（`allowAllOutbound: false`）
- Inbound: AgentCore SG からの TCP 5432 のみ許可
- **最小権限の原則** — AgentCore 以外からの DB アクセスを完全に遮断

```typescript
auroraSg.addIngressRule(
  agentCoreSg,           // ソース: AgentCore の SG
  ec2.Port.tcp(5432),    // PostgreSQL ポートのみ
  'Allow PostgreSQL from AgentCore',
);
```

### 3.5 VPC Endpoint 設計

NAT Gateway を使わずに AWS サービスにアクセスするため、3 つの Interface 型 VPC Endpoint を配置しています。

```
AgentCore Runtime
  │
  ├── bedrock-runtime Endpoint ──→ Amazon Bedrock（Claude Sonnet 4 呼び出し）
  │
  ├── logs Endpoint ────────────→ CloudWatch Logs（ログ出力）
  │
  └── secretsmanager Endpoint ──→ Secrets Manager（DB認証情報の取得）
```

| VPC Endpoint | AWS サービス | 用途 |
|:-------------|:------------|:-----|
| `bedrock-runtime` | Amazon Bedrock | Claude Sonnet 4 の推論呼び出し |
| `logs` | CloudWatch Logs | AgentCore ランタイムのログ出力 |
| `secretsmanager` | Secrets Manager | Aurora の DB 認証情報（host, username, password）の取得 |

#### VPC Endpoint が必要な理由

```
PRIVATE_ISOLATED サブネット
  → インターネットへのルートがない
  → NAT Gateway もない
  → AWS サービスの API エンドポイントに到達できない
  → VPC Endpoint で AWS サービスへのプライベート経路を確保
```

#### VPC Endpoint のタイプ

| タイプ | 仕組み | 本プロジェクトでの使用 |
|:-------|:------|:--------------------|
| **Interface 型** | サブネット内に ENI を作成し、プライベート IP でアクセス | Bedrock、Logs、Secrets Manager |
| **Gateway 型** | ルートテーブルにエントリを追加 | 未使用（S3、DynamoDB 用） |

Interface 型 VPC Endpoint は ENI を各サブネットに作成するため、サブネット数 × エンドポイント数 の ENI が生成されます。

> **コスト注意:** Interface 型 VPC Endpoint は ~$0.014/時間（~$10/月）× 3 = **約 $30/月** の固定費が発生します。検証後は必ず削除してください。

### 3.6 Aurora との通信経路

AgentCore Runtime から Aurora への通信は、VPC 内部のプライベートネットワークで完結します。

```
AgentCore Runtime (Private Subnet)
  │
  │ 1. Secrets Manager VPC Endpoint 経由で DB 認証情報を取得
  │    → get_db_config() が SecretId から host, username, password を取得
  │
  │ 2. Aurora クラスターエンドポイントに TCP 5432 で接続
  │    → psycopg2.connect() で PostgreSQL に接続
  │    → AgentCore SG → Aurora SG の Inbound ルールで許可
  │
  │ 3. SQL を実行して結果を取得
  │    → list_tables(): information_schema からテーブル構造を取得
  │    → execute_query(): SELECT 文を実行
  │
  ▼
Aurora Serverless v2 (Private Subnet)
  PostgreSQL 16.4 / ecommerce データベース
```

### 3.7 VPC モード時の AgentCore の内部動作

AgentCore を VPC モードでデプロイすると、以下が内部的に発生します。

1. **ENI の作成**: AgentCore は指定されたサブネットに ENI（Elastic Network Interface）を作成し、VPC 内にアタッチされます
2. **プライベート IP の割り当て**: ENI にプライベート IP が割り当てられ、VPC 内のリソースと通信可能になります
3. **SG の適用**: 指定した Security Group が ENI に適用され、通信制御が有効になります

#### ENI のライフサイクル

```
agentcore deploy
  → ENI 作成（AgentCore SG がアタッチ）
  → ランタイムが ENI 経由で VPC 内に接続

agentcore destroy
  → ランタイム停止
  → ENI の解放（数分〜数時間かかることがある）
  → ⚠ ENI が残っている間は SG を削除できない
```

> **重要:** AgentCore の ENI 解放には時間がかかるため、`cleanup.sh` では ENI の解放を最大 10 分待機してから CDK スタックの削除に進みます。ENI が残っている場合、SG をスキップして CDK を削除し、後で SG を手動削除する戦略を取っています。

---

## 4. デプロイフロー

### 4.1 全体の流れ

```
Step 1: CDK デプロイ（インフラ構築）
  → VPC、Subnet、SG、VPC Endpoints、Aurora を作成
  
Step 2: サンプルデータ投入
  → RDS Data API 経由で Aurora にテーブル・データを作成

Step 3: AgentCore プロジェクト作成
  → agentcore create --network-mode VPC --subnets ... --security-groups ... で作成
  → agentcore.json に VPC 設定と環境変数が記載される

Step 4: AgentCore デプロイ
  → agentcore deploy で CDK マネージドデプロイを実行
  → 環境変数は agentcore.json の envVars で設定済み

Step 5: IAM 権限追加
  → 実行ロールに Secrets Manager の読み取り権限を追加

Step 6: 動作確認
  → agentcore invoke で自然言語クエリを実行
```

### 4.2 agentcore deploy の内部動作

agentcore CLI v0.8 では `managedBy: CDK` の CDK マネージドアプローチでデプロイが行われます。

```
agentcore deploy
  │
  ├── 1. ソースコードを ZIP (CodeZip) でパッケージング
  │      → codeLocation で指定したディレクトリを ZIP 化
  │
  ├── 2. CDK マネージドデプロイ
  │      → agentcore.json の設定に基づいてインフラを構成
  │      → pyproject.toml の dependencies をインストール
  │
  ├── 3. AgentCore Runtime にデプロイ
  │      → VPC 設定を適用（Subnet、SG を指定）
  │      → ENI を作成して VPC にアタッチ
  │      → envVars から環境変数を設定
  │
  └── 4. エンドポイントを公開
         → Endpoint: DEFAULT (READY) になれば完了
```

### 4.3 環境変数

AgentCore Runtime に渡す環境変数は `agentcore.json` の `envVars` セクションで定義します。

```json
"envVars": [
  { "name": "DB_SECRET_ARN", "value": "arn:aws:secretsmanager:..." },
  { "name": "DB_NAME", "value": "ecommerce" }
]
```

| 環境変数 | 用途 | 設定場所 |
|:---------|:-----|:---------|
| `DB_SECRET_ARN` | Secrets Manager の ARN（Aurora の認証情報） | `agentcore.json` の `envVars` |
| `DB_NAME` | データベース名（`ecommerce`） | `agentcore.json` の `envVars` |
| `AWS_REGION` | AWS リージョン | ランタイムが自動設定 |

---

## 5. セキュリティ設計

### 5.1 ネットワークレベル

- **完全プライベート**: PRIVATE_ISOLATED サブネットにより、インターネットへのルートが一切ない
- **最小権限 SG**: Aurora は AgentCore SG からの TCP 5432 のみ受け入れ
- **VPC Endpoint**: AWS サービスへの通信もプライベート経路のみ

### 5.2 認証・認可レベル

- **Secrets Manager**: DB 認証情報はハードコードせず、Secrets Manager から動的に取得
- **IAM ロール**: AgentCore の実行ロールに必要最小限の権限（Secrets Manager 読み取り、Bedrock 呼び出し）
- **SQL インジェクション防止**: `execute_query` ツールは SELECT 文のみを許可

```python
if not sql.strip().upper().startswith("SELECT"):
    return "エラー: SELECT文のみ実行可能です"
```

### 5.3 暗号化

- **Aurora ストレージ暗号化**: `storageEncrypted: true`
- **VPC Endpoint 経由通信**: TLS で暗号化
- **Secrets Manager**: KMS による暗号化

---

## 6. コストと注意点

### 6.1 リソース別コスト

| リソース | 稼働時コスト | 停止時コスト | 備考 |
|:---------|:-----------|:-----------|:-----|
| VPC Endpoint × 3 | ~$30/月 | ~$30/月 | **常時課金。検証後は削除必須** |
| Aurora Serverless v2 | ~$0.12/ACU/時 | $0 | ゼロスケール対応。アイドル時は $0 |
| Aurora ストレージ | ~$0.01/月 | ~$0.01/月 | サンプルデータは微量 |
| Secrets Manager | ~$0.40/月 | ~$0.40/月 | シークレット 1 個分 |
| VPC / Subnet / SG | $0 | $0 | 無料 |
| AgentCore Runtime | 呼び出し量に応じた課金 | $0 | アイドル時は課金なし |

### 6.2 検証時のコスト目安

- 数時間の検証: **50 円以下**
- 1 日放置: **約 $1**（VPC Endpoint の時間課金）
- 1 ヶ月放置: **約 $30**（VPC Endpoint のみ）

### 6.3 クリーンアップ

検証後は必ず `scripts/cleanup.sh` を実行してください。

```bash
./scripts/cleanup.sh
```

クリーンアップの流れ:

1. `agentcore destroy` でエージェントを削除
2. ENI の解放を最大 10 分待機
3. `cdk destroy` で CDK スタック（VPC、Aurora 等）を削除
4. 残った SG の削除を試行

> ENI 解放が間に合わない場合は、CloudFormation の強制削除も可能です:
> ```bash
> aws cloudformation delete-stack \
>   --stack-name text-to-sql-stack \
>   --deletion-mode FORCE_DELETE_STACK \
>   --region ap-northeast-1
> ```

---

## 7. Strands SDK ハング問題と boto3 ワークアラウンド

### 7.1 問題の概要

当初は Strands Agents SDK の `Agent.stream_async()` を使用してエージェントを実装していましたが、AgentCore の VPC モード内で実行すると、**応答がハングして返ってこない**問題が発生しました。

```python
# 当初の実装（VPC モードでハングする）
agent = Agent(
    model=load_model(),
    system_prompt=SYSTEM_PROMPT,
    tools=[list_tables, execute_query],
)
stream = agent.stream_async(payload.get("prompt", ""))
async for event in stream:
    if "data" in event and isinstance(event["data"], str):
        yield event["data"]    # ← ここで応答が返ってこない
```

### 7.2 原因の推測

VPC PRIVATE_ISOLATED 環境では、Strands SDK 内部の非同期ストリーミング処理がネットワーク経路（VPC Endpoint 経由）との組み合わせで正常に動作しない可能性があります。

### 7.3 ワークアラウンド

boto3 の `converse` API を直接呼び出す方式に変更しました。tool_use / tool_result のループを自前で実装しています。

```python
# 現在の実装（boto3 converse API を直接使用）
client = boto3.client("bedrock-runtime", region_name="ap-northeast-1")
result = await asyncio.get_event_loop().run_in_executor(
    None, lambda: run_agent(client, prompt)
)
yield result
```

この方式では Strands SDK を経由せず、boto3 で Bedrock の `converse` API を直接呼び出すため、VPC モードでも安定して動作します。ストリーミング応答は使えませんが、Text-to-SQL のユースケースでは完全な応答を一括で返す方式で十分です。
