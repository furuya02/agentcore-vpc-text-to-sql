# VPC Endpoint 構成

## 概要

本プロジェクトでは、VPC 内の Private Isolated サブネットからAWSサービスへアクセスするために、**NAT Gateway の代わりに VPC Endpoint（AWS PrivateLink）** を使用しています。

NAT Gateway を使わない理由:
- **コスト削減**: NAT Gateway は時間課金 + データ転送課金が発生する（約 $0.062/h = 約 $45/月）
- **セキュリティ**: VPC Endpoint はインターネットを経由せず、AWS ネットワーク内で完結する

## ネットワーク構成

```
┌─────────────────────────────────────────────────────────┐
│  VPC                                                    │
│                                                         │
│  ┌───────────────────┐  ┌───────────────────┐          │
│  │ Private Isolated   │  │ Private Isolated   │          │
│  │ Subnet (AZ-a)      │  │ Subnet (AZ-c)      │          │
│  │                     │  │                     │          │
│  │  AgentCore Runtime  │  │  AgentCore Runtime  │          │
│  │  Aurora Writer      │  │                     │          │
│  │                     │  │                     │          │
│  └────────┬────────────┘  └────────┬────────────┘          │
│           │                        │                       │
│           ▼                        ▼                       │
│  ┌─────────────────────────────────────────────┐          │
│  │         VPC Endpoints (ENI)                  │          │
│  │                                               │          │
│  │  ┌─────────────────────────────────────────┐ │          │
│  │  │  Bedrock Runtime Endpoint               │ │          │
│  │  │  com.amazonaws.ap-northeast-1.          │ │          │
│  │  │          bedrock-runtime                │ │          │
│  │  └─────────────────────────────────────────┘ │          │
│  │  ┌─────────────────────────────────────────┐ │          │
│  │  │  CloudWatch Logs Endpoint               │ │          │
│  │  │  com.amazonaws.ap-northeast-1.logs      │ │          │
│  │  └─────────────────────────────────────────┘ │          │
│  │  ┌─────────────────────────────────────────┐ │          │
│  │  │  Secrets Manager Endpoint               │ │          │
│  │  │  com.amazonaws.ap-northeast-1.          │ │          │
│  │  │          secretsmanager                 │ │          │
│  │  └─────────────────────────────────────────┘ │          │
│  └─────────────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────┘
```

## VPC Endpoint 一覧

| # | エンドポイント | サービス名 | タイプ | 用途 |
|:-:|:-------------|:----------|:------|:-----|
| 1 | BedrockRuntimeEndpoint | `com.amazonaws.ap-northeast-1.bedrock-runtime` | Interface | AgentCore から Bedrock（Claude）を呼び出すため |
| 2 | CloudWatchLogsEndpoint | `com.amazonaws.ap-northeast-1.logs` | Interface | AgentCore のログを CloudWatch Logs に出力するため |
| 3 | SecretsManagerEndpoint | `com.amazonaws.ap-northeast-1.secretsmanager` | Interface | Aurora の DB 認証情報（ユーザ名・パスワード）を Secrets Manager から取得するため |

3つすべて **Interface 型 VPC Endpoint**（AWS PrivateLink）です。各サブネットに ENI（Elastic Network Interface）が作成され、プライベート IP アドレス経由で AWS サービスと通信します。

## 各エンドポイントの詳細

### 1. Bedrock Runtime Endpoint

**目的**: AgentCore 上のエージェントが boto3 Converse API 経由で Amazon Bedrock（Claude Sonnet 4）を呼び出す際に使用。

```
AgentCore Runtime
    │
    │ Converse API (HTTPS/443)
    │ PrivateLink 経由
    ▼
Bedrock Runtime Endpoint (ENI)
    │
    ▼
Amazon Bedrock Service
```

- Text-to-SQL の中核。boto3 Converse API による自然言語 → SQL 変換、結果の要約など、すべての LLM 呼び出しがこのエンドポイントを通過する
- Inference Profile ID: `apac.anthropic.claude-sonnet-4-20250514-v1:0`

### 2. CloudWatch Logs Endpoint

**目的**: AgentCore Runtime のログ（エージェント実行ログ、エラーログ）を CloudWatch Logs に送信。

```
AgentCore Runtime
    │
    │ PutLogEvents API (HTTPS/443)
    │ PrivateLink 経由
    ▼
CloudWatch Logs Endpoint (ENI)
    │
    ▼
Amazon CloudWatch Logs Service
```

- エージェントのデバッグ・モニタリングに必要
- VPC Endpoint がないと、Isolated サブネットからはログを送信できない

### 3. Secrets Manager Endpoint

**目的**: Aurora Serverless v2 の認証情報（ユーザ名・パスワード）を Secrets Manager から安全に取得。

```
AgentCore Runtime
    │
    │ GetSecretValue API (HTTPS/443)
    │ PrivateLink 経由
    ▼
Secrets Manager Endpoint (ENI)
    │
    ▼
AWS Secrets Manager Service
    │
    ▼
Aurora DB 認証情報（JSON）
  {
    "username": "postgres",
    "password": "xxxxx",
    "host": "xxx.cluster-xxx.ap-northeast-1.rds.amazonaws.com",
    "port": 5432,
    "dbname": "ecommerce"
  }
```

- CDK が Aurora クラスター作成時に自動生成するシークレットを参照
- エージェントコード内で `boto3` の Secrets Manager クライアントを使用して取得

## CDK コード

`cdk/lib/text-to-sql-stack.ts`（51〜70行目）:

```typescript
// VPC Endpoints（NAT Gateway の代わり）

// Bedrock Runtime — LLM 呼び出し用
vpc.addInterfaceEndpoint('BedrockRuntimeEndpoint', {
  service: ec2.InterfaceVpcEndpointAwsService.BEDROCK_RUNTIME,
  subnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
});

// CloudWatch Logs — ログ出力用
vpc.addInterfaceEndpoint('CloudWatchLogsEndpoint', {
  service: ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS,
  subnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
});

// Secrets Manager — DB 認証情報取得用
vpc.addInterfaceEndpoint('SecretsManagerEndpoint', {
  service: ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER,
  subnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
});
```

## セキュリティグループ

CDK の `addInterfaceEndpoint` はデフォルトで以下のセキュリティグループを自動作成します:

- **インバウンド**: VPC CIDR（10.0.0.0/16）からの HTTPS（443）を許可
- **アウトバウンド**: すべて許可

AgentCore のセキュリティグループ（`AgentCoreSg`）は `allowAllOutbound: true` のため、各 VPC Endpoint の 443 ポートへのアクセスが許可されます。

## コスト

| 項目 | 料金（ap-northeast-1） |
|:-----|:----------------------|
| Interface VPC Endpoint（1 エンドポイント・1 AZ あたり） | $0.014/h ≒ $10.08/月 |
| 本構成（3 エンドポイント × 2 AZ） | $0.084/h ≒ **$60.48/月** |
| データ処理 | $0.01/GB |

> **補足**: 検証用途では数時間の利用で済むため、使用後に `cdk destroy` でリソースを削除すればコストは最小限に抑えられます。NAT Gateway（$0.062/h × 2 AZ = $89.28/月）と比較すると、本構成の方がやや安価です。

## なぜこの 3 つなのか？

AgentCore Runtime が VPC 内で動作する際に通信する AWS サービスは以下の 3 つです:

1. **Bedrock Runtime** — エージェントの頭脳（LLM）。これがないと SQL を生成できない
2. **CloudWatch Logs** — ログ出力。これがないとデバッグ・運用監視ができない
3. **Secrets Manager** — DB 接続情報。これがないと Aurora に接続できない

Aurora 自体は同一 VPC 内にあるため、VPC Endpoint は不要です（セキュリティグループで直接通信）。
