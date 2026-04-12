#!/usr/bin/env node
import "source-map-support/register";
import * as cdk from "aws-cdk-lib";
import { TextToSqlStack } from "../lib/text-to-sql-stack";

const app = new cdk.App();

new TextToSqlStack(app, "text-to-sql-stack", {
  env: {
    region: "ap-northeast-1",
  },
});
