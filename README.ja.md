# AgentCore VPC Text-to-SQL

AgentCore を VPC に入れて Aurora Serverless v2 に自然言語で問い合わせる Text-to-SQL エージェントです。

## アーキテクチャ

```
┌─────────────────────────────────────────────────────────────────┐
│ VPC (10.0.0.0/16)                                               │
│                                                                 │
│  ┌──────────────────────┐    ┌──────────────────────┐           │
│  │ Private Subnet 1     │    │ Private Subnet 2     │           │
│  │ (ap-northeast-1a)    │    │ (ap-northeast-1c)    │           │
│  │                      │    │                      │           │
│  │  AgentCore Runtime   │    │                      │           │
│  │  ┌────────────────┐  │    │                      │           │
│  │  │ Text-to-SQL    │  │    │                      │           │
│  │  │ Agent          │  │    │                      │           │
│  │  │ (Strands +     │  │    │                      │           │
│  │  │  Bedrock)      │  │    │                      │           │
│  │  └───┬────────┬───┘  │    │                      │           │
│  │      │        │      │    │                      │           │
│  │      │   ┌────┼──────┼────┼──────────────────┐   │           │
│  │      │   │    │   Aurora Serverless v2        │   │           │
│  │      │   │    │   (PostgreSQL 16.4)           │   │           │
│  │      │   │    └──►  EC サイト注文データ        │   │           │
│  │      │   │        - customers (50件)          │   │           │
│  │      │   │        - products (30件)           │   │           │
│  │      │   │        - orders (200件)            │   │           │
│  │      │   │        - order_items (500件)       │   │           │
│  │      │   └────────────────────────────────────┘   │           │
│  └──────┼───────────────┘    └───────────────────────┘           │
│         │                                                       │
│  ┌──────┼───────────────────────────────────────────────────┐   │
│  │ VPC Endpoints (Interface型)                               │   │
│  │  ├── bedrock-runtime ──► Amazon Bedrock (Claude Sonnet 4) │   │
│  │  ├── logs ─────────────► CloudWatch Logs                  │   │
│  │  └── secretsmanager ──► Secrets Manager (DB認証情報)       │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  Security Groups:                                               │
│  - AgentCore SG: outbound all                                   │
│  - Aurora SG: inbound 5432 from AgentCore SG のみ               │
└─────────────────────────────────────────────────────────────────┘

                    ▲
                    │ agentcore invoke '{"prompt": "売上トップ10は？"}'
                    │
                  User
```

## 前提条件

- AWS CLI v2（認証設定済み）
- Node.js 18 以上
- pnpm
- Python 3.10 以上
- AgentCore CLI (`pip install bedrock-agentcore`)
- CDK Bootstrap 済み (`pnpm exec cdk bootstrap aws://ACCOUNT_ID/ap-northeast-1`)

## 手順

### Step 1. CDK デプロイ（インフラ構築）

```bash
cd cdk
pnpm install
pnpm exec cdk deploy
```

デプロイ完了後、Outputs を控えておきます（後続の手順で使用）:

```
text-to-sql-stack.VpcId = vpc-xxxxxxxxx
text-to-sql-stack.SubnetIds = subnet-aaa,subnet-bbb
text-to-sql-stack.AgentCoreSecurityGroupId = sg-xxxxxxxxx
text-to-sql-stack.ClusterArn = arn:aws:rds:...
text-to-sql-stack.SecretArn = arn:aws:secretsmanager:...
text-to-sql-stack.ClusterEndpoint = text-to-sql-stack-auroracluster-xxx...
text-to-sql-stack.DatabaseName = ecommerce
```

### Step 2. サンプルデータの投入

```bash
cd cdk
chmod +x scripts/seed-data.sh
./scripts/seed-data.sh
```

投入されるデータ:

| テーブル | 件数 | 内容 |
|:---------|:-----|:-----|
| customers | 50 | 顧客（名前・メール・都道府県） |
| products | 30 | 商品（電子機器・衣類・食品・書籍・日用品） |
| orders | 200 | 注文（過去 90 日分） |
| order_items | 500 | 注文明細 |

### Step 3. AgentCore プロジェクトの作成

```bash
cd agent
agentcore create -p texttosql -t basic --agent-framework Strands --model-provider Bedrock --non-interactive --no-venv
```

> **注意**: プロジェクト名にハイフン (`-`) やアンダースコア (`_`) は使えません。英数字のみ、36文字以内です。

生成された `.bedrock_agentcore.yaml` を編集し、VPC 設定を追加します:

```yaml
# network_configuration セクションを以下に変更
network_configuration:
  network_mode: VPC
  network_mode_config:
    subnets:
      - （SubnetIds の値1）
      - （SubnetIds の値2）
    security_groups:
      - （AgentCoreSecurityGroupId の値）
```

> **注意**: `agentcore create` で PUBLIC モードで作成した後に `agentcore configure --vpc` で変更しようとするとエラーになります。yaml を直接編集してください。

### Step 4. AgentCore デプロイ

```bash
cd agent
agentcore deploy \
  --env "DB_SECRET_ARN=（SecretArn の値）" \
  --env "DB_NAME=ecommerce"
```

### Step 5. 実行ロールに Secrets Manager の権限を追加

`agentcore deploy` で自動作成される実行ロールには Secrets Manager へのアクセス権限が含まれていないため、手動で追加します。

```bash
# 実行ロール名は agentcore deploy の出力、または .bedrock_agentcore.yaml の
# aws.execution_role から確認できます
ROLE_NAME="（実行ロール名）"
SECRET_ARN="（SecretArn の値）"

aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "SecretsManagerReadAccess" \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": "secretsmanager:GetSecretValue",
      "Resource": "'"$SECRET_ARN"'*"
    }]
  }'
```

### Step 6. 動作確認

エンドポイントが READY になるまで待ちます:

```bash
agentcore status
# Endpoint: DEFAULT (READY) になるまで待つ
```

invoke で動作確認:

```bash
# テーブル一覧
agentcore invoke '{"prompt": "テーブル一覧を教えて"}'

# 売上クエリ
agentcore invoke '{"prompt": "売上トップ5の商品は？"}'

# 都道府県別の顧客数
agentcore invoke '{"prompt": "都道府県別の顧客数を教えて"}'
```

## クリーンアップ

**検証後は必ず実行してください。** 放置すると VPC Endpoint の課金（~$1/日）が発生します。

```bash
# プロジェクトルートから実行
./scripts/cleanup.sh
```

> **注意**: AgentCore が VPC 内に作成した ENI の解放に数分〜数時間かかることがあります。
> `cleanup.sh` は ENI 解放を待ってから CDK を削除するため、安全に実行できます。
> 待ちきれない場合は `aws cloudformation delete-stack --stack-name text-to-sql-stack --deletion-mode FORCE_DELETE_STACK --region ap-northeast-1` で強制削除できます。

### 放置時のコスト目安

| リソース | 月額 |
|:---------|:-----|
| VPC Endpoint × 3 | ~$30 |
| Aurora ACU | $0（ゼロスケールで自動停止） |
| Aurora ストレージ | ~$0.01 |
| Secrets Manager | ~$0.40 |
| VPC / Subnet / SG | $0 |
