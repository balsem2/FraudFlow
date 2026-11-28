# FraudFlow AWS Terraform

This configuration describes the AWS path:

```text
aws_producer -> Kinesis -> detection Lambda -> SageMaker -> DynamoDB
                                      |                         |
                                      +-> SQS FIFO -> Bedrock investigation Lambda
Streamlit on ECS/Fargate -------------------------------> DynamoDB/SageMaker/SQS
```

The code is local only. No `terraform apply`, image push, endpoint deployment,
or real Bedrock invocation has been performed. AWS Academy permissions, service
quotas, Bedrock model access, and exact regional availability remain unverified.

## What Terraform manages

- Private ECR repositories for inference and dashboard images.
- A private encrypted/versioned S3 bucket and upload of
  `artifacts/sagemaker/model.tar.gz`.
- An on-demand Kinesis stream, DynamoDB table and indexes, SQS alert FIFO queue,
  FIFO DLQ, and Kinesis failure queue.
- Zipped Lambda code, event-source mappings, scoped IAM roles/policies, log
  groups, and basic Lambda error alarms.
- SageMaker model/endpoint and ECS/Fargate service behind explicit opt-in flags.

Terraform uploads the model archive and packages Lambda source. It does **not**
build or push Docker images, provision the BankSim source data to Kinesis, create
HTTPS/authentication, or configure GitHub Actions deployment. The ECR repositories
must exist before images can be pushed. The SageMaker endpoint is always-on and
billable while enabled. DynamoDB point-in-time recovery, network resources,
Kinesis/SQS, logs, and data transfer can also incur charges.

## Local checks

From `infra/terraform` in PowerShell:

```powershell
terraform init
terraform fmt -check -recursive
terraform validate
```

`init` downloads and locks the AWS and archive providers. These commands do not
create AWS resources. `terraform plan` uses the selected AWS credentials because
the configuration reads the account identity; it may fail if Academy verification
or permissions are incomplete. Review every plan before any apply.

Generate the S3 model artifact before planning:

```powershell
Set-Location ..\..
.\.venv\Scripts\python.exe .\scripts\package_sagemaker_model.py
Set-Location .\infra\terraform
```

Terraform reads `..\..\artifacts\sagemaker\model.tar.gz` from the workstation
during planning/applying and uploads it to the private S3 bucket. Keep the
generated archive and Terraform state out of public locations.

## Staged delivery (only after AWS access and cost review)

1. Review `terraform plan`; confirm all required IAM actions are allowed by the
   Academy role. `terraform apply` creates the base resources even though the
   SageMaker endpoint, Kinesis consumer, Bedrock consumer, and ECS service default
   to disabled. The base resources include DynamoDB point-in-time recovery,
   Kinesis, Lambda, SQS, VPC/subnets, ECR, and S3. Do not apply merely to test
   access.
2. After ECR repositories exist, build and push the inference image. From the
   repository root, use the repository URL from Terraform output:

   ```powershell
   $region = "eu-north-1"
   $inferenceRepo = terraform -chdir=infra/terraform output -raw inference_ecr_repository_url
   aws ecr get-login-password --region $region |
     docker login --username AWS --password-stdin (($inferenceRepo -split '/')[0])
   docker build -f Dockerfile.inference -t "${inferenceRepo}:v1" .
   docker push "${inferenceRepo}:v1"
   ```

3. Only after the image is pushed and the model archive exists, enable
   `enable_sagemaker_endpoint = true` and apply. Verify the endpoint is
   `InService` before continuing; disable/delete it when not in use to stop its
   ongoing instance charge.
4. Enable `enable_kinesis_processing = true` to attach the detector to Kinesis.
   The producer uses the Terraform output:

   ```powershell
   $env:FRAUDFLOW_KINESIS_STREAM = terraform -chdir=infra/terraform output -raw kinesis_stream_name
   .\.venv\Scripts\python.exe -m fraudflow.aws_producer --run-id demo-001 --region eu-north-1
   ```

5. Confirm the selected Bedrock model/profile is available and permitted in
   `bedrock_region`. Then set `enable_bedrock_investigation = true`. This enables
   the SQS event source mapping; alert processing can make billable Bedrock calls.
6. Build and push the AWS dashboard image:

   ```powershell
   $dashboardRepo = terraform -chdir=infra/terraform output -raw dashboard_ecr_repository_url
   docker build -f Dockerfile.aws -t "${dashboardRepo}:v1" .
   docker push "${dashboardRepo}:v1"
   ```

   Set `dashboard_allowed_cidr` to your current public IPv4 `/32` (not
   `127.0.0.1/32`) and then set `enable_dashboard_service = true`. The service
   uses a dynamic task public IP; find the running task's ENI/public IPv4 in the
   ECS console and open port 8501. This is HTTP without authentication and is
   only a restricted demo, not production-ready.

## Inputs and safety notes

- `enable_sagemaker_endpoint`, `enable_kinesis_processing`,
  `enable_bedrock_investigation`, and `enable_dashboard_service` default to
  `false`. Terraform checks that the SageMaker endpoint is enabled before
  enabling its event consumer or the dashboard.
- `dashboard_allowed_cidr` defaults to loopback as a fail-closed setting. Replace
  it with a single trusted public IPv4 `/32` only when intentionally launching
  the dashboard.
- `bedrock_region`, `bedrock_model_id`, and optional `bedrock_model_arn` must be
  set to an actually allowed model/profile. The default is a placeholder for
  configuration, not confirmation of Academy access.
- The AWS Academy role may prohibit creating IAM roles/policies or passing roles.
  Terraform does not silently substitute a broad LabRole.
- Terraform state is local by default. Do not commit `.terraform/`, state files,
  plans, AWS credentials, or model/customer data. No remote state or CI deploy
  workflow is configured.
- The dashboard service has no TLS, authentication, stable public address, or
  ALB. Do not expose it broadly. The ECR images must be pushed before enabling
  either the SageMaker endpoint or ECS service.
