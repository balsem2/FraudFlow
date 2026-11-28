resource "aws_ecr_repository" "inference" {
  name                 = "${var.project_name}-inference"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = local.common_tags
}

resource "aws_ecr_repository" "dashboard" {
  name                 = "${var.project_name}-dashboard"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = local.common_tags
}

resource "aws_s3_bucket" "model_artifacts" {
  bucket = "${var.project_name}-model-${data.aws_caller_identity.current.account_id}-${var.aws_region}"

  tags = local.common_tags
}

resource "aws_s3_bucket_public_access_block" "model_artifacts" {
  bucket = aws_s3_bucket.model_artifacts.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "model_artifacts" {
  bucket = aws_s3_bucket.model_artifacts.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "model_artifacts" {
  bucket = aws_s3_bucket.model_artifacts.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_object" "model_artifact" {
  bucket                 = aws_s3_bucket.model_artifacts.id
  key                    = "models/model.tar.gz"
  source                 = local.model_archive_path
  source_hash            = filemd5(local.model_archive_path)
  server_side_encryption = "AES256"
  content_type           = "application/gzip"

  depends_on = [
    aws_s3_bucket_public_access_block.model_artifacts,
    aws_s3_bucket_server_side_encryption_configuration.model_artifacts,
  ]
}
