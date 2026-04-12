# Aurora Serverless v2 の構成

CDK でデプロイされる Aurora Serverless v2 の設定内容を説明します。

## クラスター設定

| 項目 | 設定値 | 説明 |
|:-----|:------|:-----|
| エンジン | Aurora PostgreSQL | RDS ではなく Aurora を選択 |
| エンジンバージョン | 16.4 | ゼロスケール（ACU 0）には 16.4 以上が必要 |
| インスタンスタイプ | Serverless v2 | プロビジョンドではなくサーバーレス |
| 最小 ACU | 0 | ゼロスケール対応（未使用時は ACU 課金ゼロ） |
| 最大 ACU | 1 | 検証用途には十分。本番では要件に応じて増やす |
| データベース名 | ecommerce | デフォルトデータベースとして自動作成 |

## ネットワーク・セキュリティ設定

| 項目 | 設定値 | 説明 |
|:-----|:------|:-----|
| VPC | CDK で作成した VPC | 同一 VPC 内で AgentCore と通信 |
| サブネット | Private Isolated × 2 | Multi-AZ 構成（ap-northeast-1a, 1c） |
| セキュリティグループ | Aurora SG | AgentCore SG からの 5432 のみ許可 |
| ストレージ暗号化 | 有効 | `storageEncrypted: true` |
| パブリックアクセス | なし | Private Subnet に配置 |

## 運用・コスト設定

| 項目 | 設定値 | 説明 |
|:-----|:------|:-----|
| Data API | 有効 | VPC 外からの SQL 実行が可能（データ投入・動作確認用） |
| 削除保護 | 無効 | 検証用途のため `deletionProtection: false` |
| バックアップ保持期間 | 1 日 | 最小限（検証用途） |
| 削除ポリシー | DESTROY | `cdk destroy` で完全削除可能 |
| 認証情報 | Secrets Manager | CDK が自動生成。エージェントコードから取得して使用 |

## データベース構成

### ER 図

```
customers          orders              order_items         products
+-------------+   +-------------+     +--------------+    +-------------+
| customer_id |◄--| customer_id |     | order_item_id|    | product_id  |
| name        |   | order_id    |◄----| order_id     |    | name        |
| email       |   | order_date  |     | product_id   |---►| category    |
| prefecture  |   | total_amount|     | quantity      |    | price       |
| created_at  |   | status      |     | unit_price    |    | stock       |
+-------------+   +-------------+     +--------------+    +-------------+
```

### テーブル詳細

#### customers（顧客）

| カラム | 型 | 説明 |
|:-------|:---|:-----|
| customer_id | SERIAL PRIMARY KEY | 顧客 ID |
| name | VARCHAR(100) | 氏名（例: 佐藤 太郎） |
| email | VARCHAR(200) | メールアドレス |
| prefecture | VARCHAR(50) | 都道府県（東京都、大阪府 等） |
| created_at | TIMESTAMP | 登録日時 |

サンプルデータ: 50 件（10 姓 × 5 名の組み合わせ、10 都道府県）

#### products（商品）

| カラム | 型 | 説明 |
|:-------|:---|:-----|
| product_id | SERIAL PRIMARY KEY | 商品 ID |
| name | VARCHAR(200) | 商品名 |
| category | VARCHAR(100) | カテゴリ |
| price | INTEGER | 価格（円） |
| stock | INTEGER | 在庫数 |

サンプルデータ: 30 件（5 カテゴリ × 6 商品）

| カテゴリ | 商品例 | 価格帯 |
|:---------|:-------|:------|
| 電子機器 | ワイヤレスイヤホン、スマートウォッチ | ¥2,980〜¥24,800 |
| 衣類 | カシミヤセーター、コットンTシャツ | ¥2,980〜¥18,800 |
| 食品 | 有機抹茶パウダー、黒毛和牛すき焼きセット | ¥2,480〜¥12,800 |
| 書籍 | Python実践入門、AWS設計パターン | ¥1,680〜¥4,280 |
| 日用品 | ステンレス水筒、今治タオルセット | ¥3,280〜¥8,980 |

#### orders（注文）

| カラム | 型 | 説明 |
|:-------|:---|:-----|
| order_id | SERIAL PRIMARY KEY | 注文 ID |
| customer_id | INTEGER FK | 顧客 ID |
| order_date | DATE | 注文日 |
| total_amount | INTEGER | 合計金額（order_items から自動計算） |
| status | VARCHAR(50) | completed / cancelled / pending |

サンプルデータ: 200 件（過去 90 日分、completed が約 67%）

#### order_items（注文明細）

| カラム | 型 | 説明 |
|:-------|:---|:-----|
| order_item_id | SERIAL PRIMARY KEY | 注文明細 ID |
| order_id | INTEGER FK | 注文 ID |
| product_id | INTEGER FK | 商品 ID |
| quantity | INTEGER | 数量（1〜5） |
| unit_price | INTEGER | 購入時単価 |

サンプルデータ: 500 件（各注文に平均 2.5 明細）

## コスト

### 検証中（数時間利用）

| 項目 | コスト |
|:-----|:------|
| ACU | ~$0.06（0.5 ACU × 1 時間程度のアクティブ時間） |
| ストレージ | ~$0.01 |
| I/O | ~$0.01 |
| **合計** | **約 $0.08（約 12 円）** |

### 放置時（ゼロスケール状態）

| 項目 | 月額コスト |
|:-----|:----------|
| ACU | $0（ゼロスケールで自動停止） |
| ストレージ | ~$0.01（サンプルデータ数 MB 分） |
| Secrets Manager | ~$0.40 |
| **合計** | **約 $0.41/月（約 60 円）** |

### 注意: コールドスタート

ゼロスケール（0 ACU）状態から最初のクエリを実行すると、Aurora がスケールアップするまでに **数十秒のコールドスタート** が発生します。AgentCore のタイムアウト設定に注意してください。

## ブログ用スクリーンショット

以下のスクリーンショットを撮ると、ブログ記事で説明しやすくなります。

### 1. RDS クラスター一覧画面
- **場所**: AWS コンソール → RDS → データベース
- **内容**: 作成されたクラスターが表示されている画面
- **ポイント**: クラスター名、エンジン、ステータス（Available）が見える状態

### 2. クラスターの設定タブ
- **場所**: クラスターを選択 → 「設定」タブ
- **内容**: エンジンバージョン（Aurora PostgreSQL 16.4）、DB クラスター識別子
- **ポイント**: Serverless v2 であることが確認できる箇所

### 3. キャパシティ設定（Serverless v2）
- **場所**: クラスターを選択 → 「設定」タブ内の「キャパシティ設定」セクション、またはインスタンスを選択 → 「設定」タブ
- **内容**: 最小 ACU: 0、最大 ACU: 1 の設定値
- **ポイント**: ゼロスケール（0 ACU）が設定されていることを強調

### 4. ネットワーク・セキュリティ設定
- **場所**: クラスターを選択 → 「接続とセキュリティ」タブ
- **内容**: VPC、サブネットグループ、セキュリティグループ
- **ポイント**: Private Subnet に配置されていること、パブリックアクセスが「なし」であること

### 5. セキュリティグループのインバウンドルール
- **場所**: EC2 コンソール → セキュリティグループ → Aurora SG → インバウンドルール
- **内容**: PostgreSQL (5432) が AgentCore SG からのみ許可されている
- **ポイント**: 最小権限の原則に従っている

### 6. Data API の有効化確認
- **場所**: クラスターを選択 → 「設定」タブ → 「RDS Data API」セクション
- **内容**: Data API が「有効」になっている
- **ポイント**: VPC 外からのデータ投入に使用していることを説明

### 7. Secrets Manager のシークレット
- **場所**: AWS コンソール → Secrets Manager → シークレット一覧
- **内容**: CDK が自動作成した Aurora 認証情報のシークレット
- **ポイント**: シークレット名、ローテーション設定、関連する RDS クラスター

### 8. モニタリング画面（ACU 推移）
- **場所**: クラスターを選択 → 「モニタリング」タブ → 「ServerlessDatabaseCapacity」
- **内容**: ACU の推移グラフ
- **ポイント**: agentcore invoke 実行時に ACU が 0 → 0.5〜1 に上がり、しばらくすると 0 に戻る様子
- **撮影タイミング**: invoke を数回実行した後、30 分程度待ってから撮影するとゼロスケールの動きが見える

### 9. クエリエディタ（Data API 経由）
- **場所**: RDS コンソール → クエリエディタ
- **内容**: Data API 経由でサンプルクエリを実行した結果
- **ポイント**: `SELECT * FROM products LIMIT 5` などの結果が表示されている画面。Bastion Host なしでクエリ実行できることを示す

### 10. CloudFormation のリソース一覧
- **場所**: CloudFormation → text-to-sql-stack → リソース
- **内容**: Aurora 関連のリソース（DBCluster, DBInstance, DBSubnetGroup, Secret）
- **ポイント**: CDK で一括管理されていることを示す
