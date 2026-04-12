import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as rds from 'aws-cdk-lib/aws-rds';
import { Construct } from 'constructs';

export class TextToSqlStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // -------------------------------------------------------
    // VPC — Private Isolated サブネットのみ（NAT Gateway なし）
    // -------------------------------------------------------
    const vpc = new ec2.Vpc(this, 'Vpc', {
      maxAzs: 2,
      natGateways: 0,
      subnetConfiguration: [
        {
          name: 'Private',
          subnetType: ec2.SubnetType.PRIVATE_ISOLATED,
          cidrMask: 24,
        },
      ],
    });

    // -------------------------------------------------------
    // Security Groups
    // -------------------------------------------------------

    // AgentCore Runtime 用（agentcore configure --security-groups で指定）
    const agentCoreSg = new ec2.SecurityGroup(this, 'AgentCoreSg', {
      vpc,
      description: 'Security group for AgentCore Runtime',
      allowAllOutbound: true,
    });

    // Aurora 用
    const auroraSg = new ec2.SecurityGroup(this, 'AuroraSg', {
      vpc,
      description: 'Security group for Aurora Serverless v2',
      allowAllOutbound: false,
    });

    // AgentCore → Aurora:5432 のみ許可
    auroraSg.addIngressRule(
      agentCoreSg,
      ec2.Port.tcp(5432),
      'Allow PostgreSQL from AgentCore',
    );

    // -------------------------------------------------------
    // VPC Endpoints（NAT Gateway の代わり）
    // -------------------------------------------------------

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

    // -------------------------------------------------------
    // Aurora Serverless v2 (PostgreSQL)
    // -------------------------------------------------------
    const cluster = new rds.DatabaseCluster(this, 'AuroraCluster', {
      engine: rds.DatabaseClusterEngine.auroraPostgres({
        version: rds.AuroraPostgresEngineVersion.VER_16_4,
      }),
      serverlessV2MinCapacity: 0,   // ゼロスケール（コスト最小化）
      serverlessV2MaxCapacity: 1,   // 検証用途には十分
      writer: rds.ClusterInstance.serverlessV2('writer'),
      vpc,
      vpcSubnets: {
        subnetType: ec2.SubnetType.PRIVATE_ISOLATED,
      },
      securityGroups: [auroraSg],
      defaultDatabaseName: 'ecommerce',
      enableDataApi: true,          // VPC 外からのデータ投入・確認用
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      deletionProtection: false,
      backup: {
        retention: cdk.Duration.days(1),
      },
      storageEncrypted: true,
    });

    // -------------------------------------------------------
    // Outputs — agentcore configure / seed スクリプトで使用
    // -------------------------------------------------------
    new cdk.CfnOutput(this, 'VpcId', {
      value: vpc.vpcId,
    });

    new cdk.CfnOutput(this, 'SubnetIds', {
      value: vpc.isolatedSubnets.map(s => s.subnetId).join(','),
      description: 'agentcore configure --subnets に指定',
    });

    new cdk.CfnOutput(this, 'AgentCoreSecurityGroupId', {
      value: agentCoreSg.securityGroupId,
      description: 'agentcore configure --security-groups に指定',
    });

    new cdk.CfnOutput(this, 'ClusterArn', {
      value: cluster.clusterArn,
    });

    new cdk.CfnOutput(this, 'SecretArn', {
      value: cluster.secret!.secretArn,
    });

    new cdk.CfnOutput(this, 'ClusterEndpoint', {
      value: cluster.clusterEndpoint.hostname,
    });

    new cdk.CfnOutput(this, 'DatabaseName', {
      value: 'ecommerce',
    });
  }
}
