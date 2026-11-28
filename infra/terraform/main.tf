data "aws_caller_identity" "current" {}

locals {
  common_tags = {
    Project   = "FraudFlow"
    ManagedBy = "Terraform"
  }
  model_archive_path = abspath("${path.module}/../../artifacts/sagemaker/model.tar.gz")
  bedrock_model_arn = var.bedrock_model_arn != "" ? var.bedrock_model_arn : (
    "arn:aws:bedrock:${var.bedrock_region}::foundation-model/${var.bedrock_model_id}"
  )
}
