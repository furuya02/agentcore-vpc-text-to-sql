import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as rds from 'aws-cdk-lib/aws-rds';
import { Construct } from 'constructs';

export class TextToSqlStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // VPC — Private Isolated のみ、NAT Gateway なし
    const vpc = new ec2.Vpc(this, 'Vpc', {
      maxAzs: 2,
      natGateways: 0,
      subnetConfiguration: [
        { name: 'Private', subnetType: ec2.SubnetType.PRIVATE_ISOLATED, cidrMask: 24 },
      ],
    });

    // Security Groups
    const agentCoreSg = new ec2.SecurityGroup(this, 'AgentCoreSg', { vpc, allowAllOutbound: true });
    const auroraSg = new ec2.SecurityGroup(this, 'AuroraSg', { vpc, allowAllOutbound: false });
    auroraSg.addIngressRule(agentCoreSg, ec2.Port.tcp(5432), 'Allow PostgreSQL from AgentCore');

    // VPC Endpoints（NAT Gateway の代わり）
    const isolated = { subnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED } };
    vpc.addInterfaceEndpoint('BedrockRuntime', { service: ec2.InterfaceVpcEndpointAwsService.BEDROCK_RUNTIME, ...isolated });
    vpc.addInterfaceEndpoint('CloudWatchLogs', { service: ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS, ...isolated });
    vpc.addInterfaceEndpoint('SecretsManager', { service: ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER, ...isolated });

    // Aurora Serverless v2
    const cluster = new rds.DatabaseCluster(this, 'AuroraCluster', {
      engine: rds.DatabaseClusterEngine.auroraPostgres({ version: rds.AuroraPostgresEngineVersion.VER_16_4 }),
      serverlessV2MinCapacity: 0,
      serverlessV2MaxCapacity: 1,
      writer: rds.ClusterInstance.serverlessV2('writer'),
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      securityGroups: [auroraSg],
      defaultDatabaseName: 'ecommerce',
      enableDataApi: true,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      deletionProtection: false,
      storageEncrypted: true,
    });

    // Outputs
    new cdk.CfnOutput(this, 'SubnetIds', { value: vpc.isolatedSubnets.map(s => s.subnetId).join(',') });
    new cdk.CfnOutput(this, 'AgentCoreSecurityGroupId', { value: agentCoreSg.securityGroupId });
    new cdk.CfnOutput(this, 'ClusterArn', { value: cluster.clusterArn });
    new cdk.CfnOutput(this, 'SecretArn', { value: cluster.secret!.secretArn });
  }
}
