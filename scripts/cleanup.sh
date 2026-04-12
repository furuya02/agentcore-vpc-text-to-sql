#!/bin/bash
set -euo pipefail

# ============================================================
# 全リソースを安全に削除するクリーンアップスクリプト
# 1. AgentCore を削除
# 2. AgentCore の ENI 解放を待機
# 3. CDK スタックを削除
# ============================================================

STACK_NAME="text-to-sql-stack"
REGION="ap-northeast-1"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
AGENT_DIR="${PROJECT_DIR}/agent"
CDK_DIR="${PROJECT_DIR}/cdk"

echo "=== クリーンアップ開始 ==="
echo ""

# -------------------------------------------------------
# 1. AgentCore の削除
# -------------------------------------------------------
echo "--- Step 1: AgentCore の削除 ---"
if [ -f "${AGENT_DIR}/.bedrock_agentcore.yaml" ]; then
  cd "$AGENT_DIR"
  echo "y" | agentcore destroy 2>&1 || true
  echo "  AgentCore 削除完了"
else
  echo "  .bedrock_agentcore.yaml が見つかりません（スキップ）"
fi
echo ""

# -------------------------------------------------------
# 2. AgentCore の ENI 解放を待機
# -------------------------------------------------------
echo "--- Step 2: AgentCore の ENI 解放を待機 ---"

# CDK スタックから AgentCore SG ID を取得
SG_ID=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --query 'Stacks[0].Outputs[?OutputKey==`AgentCoreSecurityGroupId`].OutputValue' \
  --output text 2>/dev/null || echo "")

if [ -z "$SG_ID" ] || [ "$SG_ID" = "None" ]; then
  echo "  SG ID を取得できません（スタック未デプロイ or 既に削除済み）"
  echo "  ENI 待機をスキップ"
else
  echo "  SG: ${SG_ID}"
  MAX_WAIT=600  # 最大10分
  INTERVAL=15
  ELAPSED=0

  while true; do
    ENI_COUNT=$(aws ec2 describe-network-interfaces \
      --filters "Name=group-id,Values=${SG_ID}" \
      --region "$REGION" \
      --query 'length(NetworkInterfaces)' \
      --output text 2>/dev/null || echo "0")

    if [ "$ENI_COUNT" = "0" ]; then
      echo "  ENI が全て解放されました"
      break
    fi

    if [ "$ELAPSED" -ge "$MAX_WAIT" ]; then
      echo "  ⚠ ${MAX_WAIT}秒待ちましたが ENI が ${ENI_COUNT} 個残っています"
      echo "  CDK destroy で SG をスキップして続行します"
      break
    fi

    echo "  ENI ${ENI_COUNT} 個が残っています（${ELAPSED}/${MAX_WAIT}秒経過）..."
    sleep "$INTERVAL"
    ELAPSED=$((ELAPSED + INTERVAL))
  done
fi
echo ""

# -------------------------------------------------------
# 3. CDK スタックの削除
# -------------------------------------------------------
echo "--- Step 3: CDK スタックの削除 ---"
cd "$CDK_DIR"

# スタックが存在するか確認
STACK_STATUS=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --query 'Stacks[0].StackStatus' \
  --output text 2>/dev/null || echo "NOT_FOUND")

if [ "$STACK_STATUS" = "NOT_FOUND" ]; then
  echo "  スタックは既に削除されています"
elif [ "$STACK_STATUS" = "DELETE_FAILED" ]; then
  echo "  前回の削除が失敗しています。SG をスキップして再削除..."
  aws cloudformation delete-stack \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --retain-resources AgentCoreSgBDF7C9EF
  echo "  削除を開始しました。完了を待機中..."
  aws cloudformation wait stack-delete-complete \
    --stack-name "$STACK_NAME" \
    --region "$REGION" 2>/dev/null || true
  echo "  スタック削除完了"
else
  echo "  pnpm exec cdk destroy を実行..."
  pnpm exec cdk destroy --force 2>&1

  # 削除失敗した場合は SG スキップで再試行
  FINAL_STATUS=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query 'Stacks[0].StackStatus' \
    --output text 2>/dev/null || echo "NOT_FOUND")

  if [ "$FINAL_STATUS" = "DELETE_FAILED" ]; then
    echo "  SG 削除に失敗。SG をスキップして再削除..."
    aws cloudformation delete-stack \
      --stack-name "$STACK_NAME" \
      --region "$REGION" \
      --retain-resources AgentCoreSgBDF7C9EF
    aws cloudformation wait stack-delete-complete \
      --stack-name "$STACK_NAME" \
      --region "$REGION" 2>/dev/null || true
    echo "  スタック削除完了（SG は手動削除が必要）"
  fi
fi
echo ""

# -------------------------------------------------------
# 4. 残った SG の削除を試みる
# -------------------------------------------------------
if [ -n "$SG_ID" ] && [ "$SG_ID" != "None" ]; then
  echo "--- Step 4: 残った SG の削除 ---"
  aws ec2 delete-security-group \
    --group-id "$SG_ID" \
    --region "$REGION" 2>/dev/null \
    && echo "  SG ${SG_ID} を削除しました" \
    || echo "  SG ${SG_ID} はまだ削除できません（ENI 解放後に手動で削除してください）"
  echo ""
fi

echo "=== クリーンアップ完了 ==="
