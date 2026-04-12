# サンプルデータの説明

## 概要

EC サイトの注文データを想定した 4 テーブル構成のサンプルデータです。`cdk/scripts/seed-data.sh` で Aurora Data API 経由で投入します。

| テーブル | 件数 | 内容 |
|:---------|:-----|:-----|
| customers | 50 | 顧客 |
| products | 30 | 商品 |
| orders | 200 | 注文 |
| order_items | 500 | 注文明細 |

## テーブルごとの詳細

### customers（顧客）— 50 件

10 の姓（佐藤、鈴木、高橋、田中、伊藤、渡辺、山本、中村、小林、加藤）と 10 の名（太郎、花子、一郎、美咲、健太、陽子、大輔、恵、翔太、由美）の組み合わせで生成。

| customer_id | name | email | prefecture |
|:------------|:-----|:------|:-----------|
| 1 | 佐藤 太郎 | customer1@example.com | 東京都 |
| 2 | 鈴木 太郎 | customer2@example.com | 大阪府 |
| 3 | 高橋 太郎 | customer3@example.com | 神奈川県 |
| 4 | 田中 太郎 | customer4@example.com | 愛知県 |
| 5 | 伊藤 太郎 | customer5@example.com | 福岡県 |
| ... | ... | ... | ... |

都道府県は 10 府県に均等分配（各 5 件）:

| 都道府県 | 件数 |
|:---------|:-----|
| 東京都 | 5 |
| 大阪府 | 5 |
| 神奈川県 | 5 |
| 愛知県 | 5 |
| 福岡県 | 5 |
| 北海道 | 5 |
| 京都府 | 5 |
| 兵庫県 | 5 |
| 埼玉県 | 5 |
| 千葉県 | 5 |

### products（商品）— 30 件

5 カテゴリ × 6 商品。日本語の商品名と現実的な価格を設定。

| カテゴリ | 件数 | 価格帯 | 商品例 |
|:---------|:-----|:-------|:-------|
| 電子機器 | 6 | ¥2,980〜¥24,800 | ワイヤレスイヤホン、スマートウォッチ、モバイルバッテリー、USBハブ、ウェブカメラ、Bluetoothスピーカー |
| 衣類 | 6 | ¥2,980〜¥18,800 | カシミヤセーター、デニムジャケット、コットンTシャツ、チノパンツ、ダウンベスト、リネンシャツ |
| 食品 | 6 | ¥2,480〜¥12,800 | 有機抹茶パウダー、北海道産チーズセット、黒毛和牛すき焼きセット、魚沼産コシヒカリ 5kg、宇治抹茶スイーツ詰め合わせ、博多明太子セット |
| 書籍 | 6 | ¥1,680〜¥4,280 | Python実践入門、AWS設計パターン、データ分析の教科書、マネジメントの基本、英語学習メソッド、機械学習エンジニアリング |
| 日用品 | 6 | ¥3,280〜¥8,980 | ステンレス水筒、今治タオルセット、アロマディフューザー、珪藻土バスマット、圧力鍋、LEDデスクライト |

### orders（注文）— 200 件

過去 90 日分のランダムな注文。ステータスの分布:

| ステータス | 件数 | 割合 |
|:-----------|:-----|:-----|
| completed | 142 | 71% |
| cancelled | 37 | 18.5% |
| pending | 21 | 10.5% |

月別売上推移（completed のみ）:

| 月 | 注文数 | 売上合計 |
|:---|:-------|:---------|
| 2026-01 | 32 | ¥1,510,260 |
| 2026-02 | 53 | ¥2,770,120 |
| 2026-03 | 42 | ¥2,029,940 |
| 2026-04 | 15 | ¥631,260 |

### order_items（注文明細）— 500 件

各注文に平均 2.5 明細。数量は 1〜5 のランダム。

売上トップ 5:

| 順位 | 商品 | カテゴリ | 売上合計 | 販売数量 |
|:-----|:-----|:---------|:---------|:---------|
| 1 | スマートウォッチ | 電子機器 | ¥1,339,200 | 54 個 |
| 2 | カシミヤセーター | 衣類 | ¥790,000 | 50 個 |
| 3 | ダウンベスト | 衣類 | ¥752,000 | 40 個 |
| 4 | 黒毛和牛すき焼きセット | 食品 | ¥704,000 | 55 個 |
| 5 | リネンシャツ | 衣類 | ¥470,820 | 59 個 |

高単価商品（スマートウォッチ ¥24,800、ダウンベスト ¥18,800）が売上上位に来る傾向。

## データの生成方法

### 固定データ（products）

`02_seed_data.sql` に 30 件の `INSERT INTO ... VALUES` で直接定義。商品名、カテゴリ、価格、在庫数を手動設定。

### 動的データ（customers, orders, order_items）

PostgreSQL の `generate_series` と `random()` で生成。

```sql
-- 顧客: 姓名の配列 × generate_series
INSERT INTO customers (name, email, prefecture, created_at)
SELECT
  (ARRAY['佐藤','鈴木',...])[(i - 1) % 10 + 1] || ' ' ||
  (ARRAY['太郎','花子',...])[((i - 1) / 10) % 10 + 1],
  'customer' || i || '@example.com',
  (ARRAY['東京都','大阪府',...])[(i - 1) % 10 + 1],
  CURRENT_TIMESTAMP - ((random() * 365)::int || ' days')::interval
FROM generate_series(1, 50) AS s(i);
```

```sql
-- 注文明細: サブクエリで product_id を決定 → JOIN で price 取得
INSERT INTO order_items (order_id, product_id, quantity, unit_price)
SELECT sub.oid, sub.pid, sub.qty, p.price
FROM (
  SELECT
    (random() * 199)::int + 1 AS oid,
    (random() * 29)::int + 1 AS pid,
    (random() * 4)::int + 1 AS qty
  FROM generate_series(1, 500)
) sub
JOIN products p ON p.product_id = sub.pid;
```

> **注意**: `LATERAL + OFFSET random()` 方式は PostgreSQL のオプティマイザが `random()` を 1 回しか評価せず、全行が同一商品になる問題があるため、サブクエリ方式を採用。

## データの確認方法

### 方法 1: Data API（AWS CLI）

VPC 外からでも実行可能。CDK Outputs の `ClusterArn` と `SecretArn` を使用。

```bash
# 変数の設定
CLUSTER_ARN="（ClusterArn の値）"
SECRET_ARN="（SecretArn の値）"
REGION="ap-northeast-1"

# テーブル一覧
aws rds-data execute-statement \
  --resource-arn "$CLUSTER_ARN" \
  --secret-arn "$SECRET_ARN" \
  --database "ecommerce" \
  --region "$REGION" \
  --sql "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'" \
  --no-cli-pager

# 件数確認
aws rds-data execute-statement \
  --resource-arn "$CLUSTER_ARN" \
  --secret-arn "$SECRET_ARN" \
  --database "ecommerce" \
  --region "$REGION" \
  --sql "SELECT 'customers' as tbl, COUNT(*) FROM customers UNION ALL SELECT 'products', COUNT(*) FROM products UNION ALL SELECT 'orders', COUNT(*) FROM orders UNION ALL SELECT 'order_items', COUNT(*) FROM order_items" \
  --no-cli-pager

# 売上トップ 5
aws rds-data execute-statement \
  --resource-arn "$CLUSTER_ARN" \
  --secret-arn "$SECRET_ARN" \
  --database "ecommerce" \
  --region "$REGION" \
  --sql "SELECT p.name, SUM(oi.quantity * oi.unit_price) as total FROM order_items oi JOIN products p ON oi.product_id = p.product_id GROUP BY p.name ORDER BY total DESC LIMIT 5" \
  --no-cli-pager
```

### 方法 2: RDS クエリエディタ（AWS コンソール）

1. AWS コンソール → RDS → クエリエディタ
2. データベースインスタンスを選択
3. 「Secrets Manager ARN を使用して接続」を選択し、SecretArn を入力
4. データベース名: `ecommerce`
5. SQL を入力して実行

### 方法 3: AgentCore エージェント経由

デプロイ済みのエージェントに自然言語で問い合わせ。

```bash
# テーブル構造の確認
agentcore invoke '{"prompt": "テーブル一覧を教えて"}'

# データ件数の確認
agentcore invoke '{"prompt": "各テーブルのレコード数を教えて"}'

# 売上の分析
agentcore invoke '{"prompt": "売上トップ5の商品は？"}'

# 都道府県別の分析
agentcore invoke '{"prompt": "都道府県別の注文数を教えて"}'

# 月別の推移
agentcore invoke '{"prompt": "月別の売上推移を教えて"}'

# キャンセル率の分析
agentcore invoke '{"prompt": "キャンセル率が高いカテゴリはどれ？"}'
```

## 注意事項

### ゼロスケールからのコールドスタート

Aurora がゼロスケール（0 ACU）状態の場合、最初のクエリで以下のエラーが返ることがあります:

```
DatabaseResumingException: The Aurora DB instance is resuming after being auto-paused.
Please wait a few seconds and try again.
```

数十秒待ってから再実行してください。

### データの再投入

データを初期状態に戻したい場合:

```bash
# テーブルを DROP して再作成
CLUSTER_ARN="（ClusterArn の値）"
SECRET_ARN="（SecretArn の値）"

for table in order_items orders customers products; do
  aws rds-data execute-statement \
    --resource-arn "$CLUSTER_ARN" \
    --secret-arn "$SECRET_ARN" \
    --database "ecommerce" \
    --region "ap-northeast-1" \
    --sql "DROP TABLE IF EXISTS ${table} CASCADE" \
    --no-cli-pager
done

# seed-data.sh を再実行
cd cdk
./scripts/seed-data.sh
```

### ランダム性

orders と order_items は `random()` で生成しているため、投入するたびに異なるデータになります。売上ランキング等の具体的な数値はデプロイごとに変わります。
