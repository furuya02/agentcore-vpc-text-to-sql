# 動作確認

AgentCore にデプロイした Text-to-SQL エージェントの動作確認方法です。

## agentcore invoke コマンド

`agentcore invoke` で JSON ペイロードを渡してエージェントを呼び出します。

```bash
agentcore invoke '{"prompt": "（自然言語の質問）"}'
```

エージェントは以下の流れで処理します:

1. Bedrock（Claude Sonnet 4）が質問を解析
2. `list_tables` ツールでテーブル構造を取得
3. SQL を生成
4. `execute_query` ツールで Aurora に SQL を実行
5. 結果を日本語で整形して返却

## テスト 1: テーブル一覧の取得

```bash
agentcore invoke '{"prompt": "テーブル一覧を教えて"}'
```

### 実行結果

```
ECサイトのデータベースには以下の4つのテーブルがあります：

1. customers（顧客テーブル）
   - customer_id：顧客ID（整数）
   - name：顧客名（文字列）
   - email：メールアドレス（文字列）
   - prefecture：都道府県（文字列）
   - created_at：登録日時（タイムスタンプ）

2. orders（注文テーブル）
   - order_id：注文ID（整数）
   - customer_id：顧客ID（整数）
   - order_date：注文日（日付）
   - total_amount：合計金額（整数）
   - status：注文状況（文字列）

3. order_items（注文明細テーブル）
   - order_item_id：注文明細ID（整数）
   - order_id：注文ID（整数）
   - product_id：商品ID（整数）
   - quantity：数量（整数）
   - unit_price：単価（整数）

4. products（商品テーブル）
   - product_id：商品ID（整数）
   - name：商品名（文字列）
   - category：カテゴリ（文字列）
   - price：価格（整数）
   - stock：在庫数（整数）
```

### 確認ポイント

- エージェントが `list_tables` ツールを呼び出し、Aurora に接続してスキーマ情報を取得できている
- VPC Endpoint 経由で Bedrock API（LLM）と Secrets Manager（DB 認証情報）にアクセスできている
- 結果を日本語で整形して返している

## テスト 2: 売上トップ 5 の商品

```bash
agentcore invoke '{"prompt": "売上トップ5の商品は？"}'
```

### 実行結果

```
売上トップ5の商品をお調べしました！

1. スマートウォッチ（電子機器）
   - 売上合計：1,339,200円
   - 販売個数：54個

2. カシミヤセーター（衣類）
   - 売上合計：790,000円
   - 販売個数：50個

3. ダウンベスト（衣類）
   - 売上合計：752,000円
   - 販売個数：40個

4. 黒毛和牛すき焼きセット（食品）
   - 売上合計：704,000円
   - 販売個数：55個

5. リネンシャツ（衣類）
   - 売上合計：470,820円
   - 販売個数：59個

スマートウォッチが圧倒的な1位で、130万円を超える売上を記録しています。
衣類カテゴリの商品が多くランクインしており、
特に高単価商品が上位に位置していることがわかります。
```

### 確認ポイント

- エージェントが複数のツールを連鎖して使用している:
  1. `list_tables` でテーブル構造を確認
  2. `execute_query` で集計 SQL（JOIN + GROUP BY + ORDER BY）を生成・実行
- 生成された SQL が正しく、order_items と products を JOIN して売上を集計できている
- 結果の数値をフォーマットし、分析コメントまで付けている

## エージェントの内部動作

`agentcore invoke` 実行時、エージェント内部では以下の通信が発生しています:

```
User
  │
  │ agentcore invoke '{"prompt": "売上トップ5は？"}'
  │
  ▼
AgentCore Runtime (VPC Private Subnet)
  │
  ├──► VPC Endpoint (bedrock-runtime)
  │      → Bedrock Claude Sonnet 4 に推論リクエスト
  │      → 「list_tables を呼んでテーブル構造を確認しよう」
  │
  ├──► VPC Endpoint (secretsmanager)
  │      → Secrets Manager から DB 認証情報を取得
  │
  ├──► Aurora Serverless v2 (VPC 内直接通信)
  │      → list_tables: information_schema.columns を SELECT
  │
  ├──► VPC Endpoint (bedrock-runtime)
  │      → 「テーブル構造をもとに SQL を生成しよう」
  │      → SELECT p.name, SUM(oi.quantity * oi.unit_price) ...
  │
  ├──► Aurora Serverless v2 (VPC 内直接通信)
  │      → execute_query: 生成した SQL を実行
  │
  ├──► VPC Endpoint (bedrock-runtime)
  │      → 「結果を日本語で分かりやすく整形しよう」
  │
  ├──► VPC Endpoint (logs)
  │      → CloudWatch Logs にログ出力
  │
  ▼
User ← レスポンス返却
```

1 回の invoke で Bedrock API を **3 回**呼び出しています（ツール選択 → SQL 生成 → 結果整形）。

## その他の問い合わせ例

```bash
# 都道府県別の顧客数
agentcore invoke '{"prompt": "都道府県別の顧客数を教えて"}'

# 月別の売上推移
agentcore invoke '{"prompt": "月別の売上推移を教えて"}'

# キャンセル率の分析
agentcore invoke '{"prompt": "キャンセル率が高いカテゴリはどれ？"}'

# 特定の条件での検索
agentcore invoke '{"prompt": "東京都の顧客が購入した商品の中で一番人気なのは？"}'

# 複雑な集計
agentcore invoke '{"prompt": "カテゴリ別の平均注文単価を教えて"}'
```

## トラブルシューティング

### エンドポイントが READY でない

```bash
agentcore status
# Endpoint: DEFAULT (CREATING) → 数分待つ
# Endpoint: DEFAULT (READY)    → invoke 可能
```

### Secrets Manager 権限エラー

```
権限設定に問題があるようです。
secretsmanager:GetSecretValue への読み取り権限が必要です。
```

→ README の Step 5 を実行して実行ロールに権限を追加してください。

### Aurora コールドスタート

ゼロスケール（0 ACU）状態からの最初のクエリでタイムアウトする場合があります。もう一度 invoke を実行すれば、Aurora が起動済みのため正常に動作します。

### セッション ID

`agentcore invoke` の出力に表示される `Session` ID は、同一セッション内での会話の継続に使用されます。異なる文脈の質問をする場合は、`agentcore stop-session` で新しいセッションを開始できます。
