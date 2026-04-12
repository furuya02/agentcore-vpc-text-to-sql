# AgentCore 解説

## 1. Amazon Bedrock AgentCore とは

Amazon Bedrock AgentCore は、AI エージェントをスケーラブルにデプロイ・実行するためのマネージドランタイムサービスです。開発者はエージェントのコードに集中し、インフラ管理（コンテナ、スケーリング、ルーティング等）は AgentCore が担当します。

### 主な特徴

| 特徴 | 説明 |
|:-----|:-----|
| **マネージドランタイム** | コンテナイメージの構築・管理が不要。Python コードを直接デプロイ（`direct_code_deploy`） |
| **自動スケーリング** | リクエスト量に応じてセッション数を自動調整 |
| **VPC 対応** | VPC 内のプライベートリソース（RDS、ElastiCache 等）にアクセス可能 |
| **フレームワーク非依存** | Strands Agents、LangChain、独自フレームワーク等を自由に選択可能 |
| **ストリーミング応答** | `yield` / `async for` によるレスポンスストリーミングをネイティブサポート |

### AgentCore のコンポーネント

```
agentcore CLI
  ├── create    … プロジェクトの雛形を生成
  ├── deploy    … コードをビルド・デプロイ（CodeBuild → ECR → Runtime）
  ├── configure … 設定の変更（VPC、環境変数等）
  ├── invoke    … エージェントの呼び出し
  ├── status    … エンドポイントの状態確認
  └── destroy   … エージェントの削除
```

---

## 2. このプロジェクトでの AgentCore 構成

### 2.1 構成ファイル（`.bedrock_agentcore.yaml`）

本プロジェクトの AgentCore は以下のように構成されています。

```yaml
default_agent: text_to_sql
agents:
  text_to_sql:
    name: text_to_sql
    deployment_type: direct_code_deploy    # コードを直接デプロイ（Dockerファイル不要）
    runtime_type: PYTHON_3_10             # Python 3.10 ランタイム
    platform: linux/amd64
```

**重要な設定値:**

| 設定 | 値 | 説明 |
|:-----|:---|:-----|
| `deployment_type` | `direct_code_deploy` | ソースコードを直接デプロイ。CodeBuild が内部で依存関係を解決してコンテナイメージをビルド |
| `runtime_type` | `PYTHON_3_10` | Python 3.10 ランタイム |
| `agent_id` | `text_to_sql-fviJMg2RT9` | AgentCore が自動生成したエージェント ID |
| `protocol` | `HTTP` | サーバープロトコル |
| `memory.mode` | `NO_MEMORY` | AgentCore のビルトインメモリ機能は未使用 |

### 2.2 エージェントコード

エントリポイントは `agent/src/main.py` です。

```python
app = BedrockAgentCoreApp()

@app.entrypoint
async def invoke(payload: dict, context: object) -> None:
    agent = Agent(
        model=load_model(),                        # Bedrock (Claude Sonnet 4)
        system_prompt=SYSTEM_PROMPT,
        tools=[list_tables, execute_query],         # 2 つのツール
    )
    stream = agent.stream_async(payload.get("prompt", ""))
    async for event in stream:
        if "data" in event and isinstance(event["data"], str):
            yield event["data"]                     # ストリーミング応答
```

**処理フロー:**

1. `BedrockAgentCoreApp` がリクエストを受信
2. `payload` から `prompt` を取得
3. Strands Agent が Bedrock (Claude Sonnet 4) を使って以下を実行:
   - `list_tables` ツール: Aurora からテーブル構造を取得
   - `execute_query` ツール: 生成した SQL を Aurora で実行（SELECT のみ）
4. 結果を自然言語に変換してストリーミング返却

### 2.3 依存パッケージ

```toml
dependencies = [
    "bedrock-agentcore >= 1.0.3",     # AgentCore SDK
    "strands-agents >= 1.13.0",       # Strands エージェントフレームワーク
    "psycopg2-binary >= 2.9.0",       # PostgreSQL ドライバ
    "boto3 >= 1.35.0",                # AWS SDK（Secrets Manager 用）
]
```

### 2.4 LLM モデル設定

```python
# agent/src/model/load.py
MODEL_ID = "apac.anthropic.claude-sonnet-4-20250514-v1:0"
```

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

`.bedrock_agentcore.yaml` の `network_configuration` セクションで指定します。

```yaml
aws:
  network_configuration:
    network_mode: VPC                  # VPC モードを有効化
    network_mode_config:
      security_groups:
        - sg-0dfaf32456547f9df         # AgentCore 用 SG
      subnets:
        - subnet-059414501ee87baa2     # Private Subnet 1 (ap-northeast-1a)
        - subnet-0d95b29308468e6c7     # Private Subnet 2 (ap-northeast-1c)
```

> **注意:** `agentcore create` で PUBLIC モードで作成した後に `agentcore configure --vpc` で VPC モードに変更しようとするとエラーになることがあります。YAML を直接編集するのが確実です。

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
  → agentcore create でプロジェクト雛形を生成
  → .bedrock_agentcore.yaml に VPC 設定を追記

Step 4: AgentCore デプロイ
  → agentcore deploy でコードをビルド・デプロイ
  → 環境変数 DB_SECRET_ARN, DB_NAME を設定

Step 5: IAM 権限追加
  → 実行ロールに Secrets Manager の読み取り権限を追加

Step 6: 動作確認
  → agentcore invoke で自然言語クエリを実行
```

### 4.2 agentcore deploy の内部動作

```
agentcore deploy
  │
  ├── 1. ソースコードを S3 にアップロード
  │      → s3://bedrock-agentcore-codebuild-sources-{ACCOUNT}-{REGION}/
  │
  ├── 2. CodeBuild が起動
  │      → pyproject.toml の dependencies をインストール
  │      → コンテナイメージをビルド
  │      → ECR にプッシュ
  │
  ├── 3. AgentCore Runtime にデプロイ
  │      → VPC 設定を適用（Subnet、SG を指定）
  │      → ENI を作成して VPC にアタッチ
  │      → 環境変数を設定
  │
  └── 4. エンドポイントを公開
         → Endpoint: DEFAULT (READY) になれば完了
```

### 4.3 環境変数

AgentCore Runtime に渡す環境変数は `agentcore deploy --env` で指定します。

| 環境変数 | 用途 | 設定タイミング |
|:---------|:-----|:-------------|
| `DB_SECRET_ARN` | Secrets Manager の ARN（Aurora の認証情報） | `agentcore deploy --env` |
| `DB_NAME` | データベース名（`ecommerce`） | `agentcore deploy --env` |
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
