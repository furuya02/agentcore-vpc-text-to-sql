# AgentCore VPC Text-to-SQL

A Text-to-SQL agent that runs AgentCore inside a VPC and queries Aurora Serverless v2 using natural language.

## Architecture

![](docs/001.png)

## Prerequisites

- AWS CLI v2 (configured with credentials)
- Node.js 18 or later
- pnpm
- Python 3.10 or later
- AgentCore CLI (`pip install bedrock-agentcore`)
- CDK Bootstrap completed (`pnpm exec cdk bootstrap aws://ACCOUNT_ID/ap-northeast-1`)

## Steps

### Step 1. CDK Deploy (Infrastructure Setup)

```bash
cd cdk
pnpm install
pnpm exec cdk deploy
```

Note the Outputs after deployment (used in subsequent steps):

```
text-to-sql-stack.VpcId = vpc-xxxxxxxxx
text-to-sql-stack.SubnetIds = subnet-aaa,subnet-bbb
text-to-sql-stack.AgentCoreSecurityGroupId = sg-xxxxxxxxx
text-to-sql-stack.ClusterArn = arn:aws:rds:...
text-to-sql-stack.SecretArn = arn:aws:secretsmanager:...
text-to-sql-stack.ClusterEndpoint = text-to-sql-stack-auroracluster-xxx...
text-to-sql-stack.DatabaseName = ecommerce
```

### Step 2. Seed Sample Data

```bash
cd cdk
chmod +x scripts/seed-data.sh
./scripts/seed-data.sh
```

Data to be inserted:

| Table | Rows | Description |
|:------|:-----|:------------|
| customers | 50 | Customers (name, email, prefecture) |
| products | 30 | Products (electronics, clothing, food, books, household) |
| orders | 200 | Orders (last 90 days) |
| order_items | 500 | Order line items |

### Step 3. Create AgentCore Project

```bash
cd agent
agentcore create \
  --name texttosql \
  --framework Strands \
  --model-provider Bedrock \
  --memory none \
  --network-mode VPC \
  --subnets "(SubnetIds value 1),(SubnetIds value 2)" \
  --security-groups "(AgentCoreSecurityGroupId value)" \
  --skip-python-setup
```

> **Note**: Project names cannot contain hyphens (`-`) or underscores (`_`). Alphanumeric only, max 23 characters.

### Step 4. AgentCore Deploy

Add environment variables to `agent/texttosql/agentcore/agentcore.json` under the runtime's `envVars` field:

```json
"envVars": [
  {
    "name": "DB_SECRET_ARN",
    "value": "(SecretArn value)"
  },
  {
    "name": "DB_NAME",
    "value": "ecommerce"
  }
]
```

Then deploy:

```bash
cd agent/texttosql
agentcore deploy
```

### Step 5. Add Secrets Manager Permission to Execution Role

The execution role auto-created by `agentcore deploy` does not include Secrets Manager access. Add it manually:

```bash
# The execution role name can be found in the agentcore deploy output
# or in .bedrock_agentcore.yaml under aws.execution_role
ROLE_NAME="(execution role name)"
SECRET_ARN="(SecretArn value)"

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

### Step 6. Verify

Wait until the endpoint is READY:

```bash
agentcore status
# Wait until Endpoint: DEFAULT (READY)
```

Invoke the agent:

```bash
# List tables
agentcore invoke '{"prompt": "Show me the table list"}'

# Sales query
agentcore invoke '{"prompt": "What are the top 5 products by sales?"}'

# Customers by prefecture
agentcore invoke '{"prompt": "How many customers are there per prefecture?"}'
```

## Cleanup

**Be sure to run this after verification.** Leaving resources running will incur VPC Endpoint charges (~$1/day).

```bash
# Run from the project root
./scripts/cleanup.sh
```

> **Note**: It may take several minutes to hours for ENIs created by AgentCore inside the VPC to be released.
> `cleanup.sh` waits for ENI release before deleting the CDK stack, so it is safe to use.
> If you cannot wait, force delete with: `aws cloudformation delete-stack --stack-name text-to-sql-stack --deletion-mode FORCE_DELETE_STACK --region ap-northeast-1`

### Estimated Cost if Left Running

| Resource | Monthly Cost |
|:---------|:------------|
| VPC Endpoint × 3 | ~$30 |
| Aurora ACU | $0 (auto-paused when idle) |
| Aurora Storage | ~$0.01 |
| Secrets Manager | ~$0.40 |
| VPC / Subnet / SG | $0 |
