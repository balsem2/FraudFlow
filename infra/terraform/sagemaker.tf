resource "aws_iam_role" "sagemaker" {
  name = "${var.project_name}-sagemaker-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "sagemaker.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy" "sagemaker" {
  name = "${var.project_name}-sagemaker-access"
  role = aws_iam_role.sagemaker.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetBucketLocation", "s3:ListBucket"]
        Resource = [aws_s3_bucket.model_artifacts.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = [aws_s3_object.model_artifact.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
        ]
        Resource = [aws_ecr_repository.inference.arn]
      },
      {
        Effect = "Allow"
        Action = [
          "cloudwatch:CreateLogGroup",
          "cloudwatch:CreateLogStream",
          "cloudwatch:PutLogEvents",
          "cloudwatch:PutMetricData",
        ]
        Resource = "*"
      },
    ]
  })
}

resource "aws_sagemaker_model" "fraud" {
  count = var.enable_sagemaker_endpoint ? 1 : 0

  name               = "${var.project_name}-xgb"
  execution_role_arn = aws_iam_role.sagemaker.arn

  primary_container {
    image          = "${aws_ecr_repository.inference.repository_url}:${var.inference_image_tag}"
    model_data_url = "s3://${aws_s3_bucket.model_artifacts.bucket}/${aws_s3_object.model_artifact.key}"
  }

  tags = local.common_tags
}

resource "aws_sagemaker_endpoint_configuration" "fraud" {
  count = var.enable_sagemaker_endpoint ? 1 : 0

  name = "${var.project_name}-xgb-config"

  production_variants {
    variant_name           = "AllTraffic"
    model_name             = aws_sagemaker_model.fraud[0].name
    initial_instance_count = 1
    instance_type          = var.sagemaker_instance_type
  }

  tags = local.common_tags
}

resource "aws_sagemaker_endpoint" "fraud" {
  count = var.enable_sagemaker_endpoint ? 1 : 0

  name                 = var.sagemaker_endpoint_name
  endpoint_config_name = aws_sagemaker_endpoint_configuration.fraud[0].name

  tags = local.common_tags
}
