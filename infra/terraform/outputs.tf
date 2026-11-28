output "inference_ecr_repository_url" {
  description = "ECR URL for the SageMaker inference image."
  value       = aws_ecr_repository.inference.repository_url
}

output "dashboard_ecr_repository_url" {
  description = "ECR URL for the Streamlit dashboard image."
  value       = aws_ecr_repository.dashboard.repository_url
}

output "model_artifacts_bucket" {
  description = "Private S3 bucket for SageMaker model artifacts."
  value       = aws_s3_bucket.model_artifacts.bucket
}

output "model_artifact_s3_uri" {
  description = "S3 URI to which Terraform uploads the packaged model artifact."
  value       = "s3://${aws_s3_bucket.model_artifacts.bucket}/${aws_s3_object.model_artifact.key}"
}

output "kinesis_stream_name" {
  description = "Kinesis stream used by the event producer."
  value       = aws_kinesis_stream.transactions.name
}

output "sagemaker_endpoint_name" {
  description = "Configured endpoint name; endpoint creation is opt-in."
  value       = var.sagemaker_endpoint_name
}

output "dashboard_service_name" {
  description = "ECS service name when enabled; the task public IP is dynamic and should be checked in ECS."
  value       = var.enable_dashboard_service ? aws_ecs_service.dashboard[0].name : "ECS dashboard disabled"
}

output "aws_region" {
  description = "AWS region used by this Terraform configuration."
  value       = var.aws_region
}
