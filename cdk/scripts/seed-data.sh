#!/bin/bash
set -euo pipefail

# ============================================================
# Aurora Serverless v2 にサンプルデータを投入するスクリプト
# RDS Data API を使用（VPC 外から実行可能）
# ============================================================

STACK_NAME="text-to-sql-stack"
REGION="ap-northeast-1"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SQL_DIR="${SCRIPT_DIR}/../sql"

echo "=== CDK Stack から接続情報を取得 ==="

get_output() {
  aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey==\`$1\`].OutputValue" \
    --output text
}

CLUSTER_ARN=$(get_output "ClusterArn")
SECRET_ARN=$(get_output "SecretArn")
DB_NAME=$(get_output "DatabaseName")

echo "  Cluster ARN : ${CLUSTER_ARN}"
echo "  Secret ARN  : ${SECRET_ARN}"
echo "  Database    : ${DB_NAME}"
echo ""

# SQL ファイルを読み込み、ステートメント単位で実行
execute_sql_file() {
  local file="$1"
  local filename
  filename=$(basename "$file")
  echo "=== ${filename} を実行中 ==="

  # コメント除去 → セミコロンで分割 → 一時ファイル経由で実行
  local tmpdir
  tmpdir=$(mktemp -d)
  sed 's/--.*$//' "$file" | \
    awk -v dir="$tmpdir" 'BEGIN{RS=";"} {gsub(/^[[:space:]]+|[[:space:]]+$/, ""); if(length($0) > 0) {n++; f=dir"/stmt_"n".sql"; print $0 > f; close(f)}}'

  local count=0
  for stmt_file in $(ls "$tmpdir"/stmt_*.sql 2>/dev/null | sort -t_ -k2 -n); do
    [ -f "$stmt_file" ] || continue
    count=$((count + 1))
    local oneline
    oneline=$(tr '\n' ' ' < "$stmt_file" | sed 's/  */ /g')
    echo "  [${count}] ${oneline:0:70}..."
    local sql
    sql=$(cat "$stmt_file")
    aws rds-data execute-statement \
      --resource-arn "$CLUSTER_ARN" \
      --secret-arn "$SECRET_ARN" \
      --database "$DB_NAME" \
      --region "$REGION" \
      --sql "$sql" \
      --no-cli-pager > /dev/null
  done
  rm -rf "$tmpdir"

  echo "  完了"
  echo ""
}

execute_sql_file "${SQL_DIR}/01_schema.sql"
execute_sql_file "${SQL_DIR}/02_seed_data.sql"

# 投入結果の確認
echo "=== データ件数の確認 ==="
for table in customers products orders order_items; do
  result=$(aws rds-data execute-statement \
    --resource-arn "$CLUSTER_ARN" \
    --secret-arn "$SECRET_ARN" \
    --database "$DB_NAME" \
    --region "$REGION" \
    --sql "SELECT COUNT(*) AS cnt FROM ${table}" \
    --no-cli-pager \
    --output json)
  count=$(echo "$result" | grep -o '"longValue": *[0-9]*' | head -1 | sed 's/.*: *//')
  echo "  ${table}: ${count} 件"
done

echo ""
echo "=== サンプルデータの投入が完了しました ==="
