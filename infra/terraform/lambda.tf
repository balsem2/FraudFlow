data "archive_file" "detection" {
  type        = "zip"
  output_path = "${path.module}/.terraform/detection.zip"

  source {
    content  = file("${path.module}/../../fraudflow/__init__.py")
    filename = "fraudflow/__init__.py"
  }
  source {
    content  = file("${path.module}/../../fraudflow/contract.py")
    filename = "fraudflow/contract.py"
  }
  source {
    content  = file("${path.module}/../../fraudflow/lambda_detection.py")
    filename = "fraudflow/lambda_detection.py"
  }
}

data "archive_file" "investigation" {
  type        = "zip"
  output_path = "${path.module}/.terraform/investigation.zip"

  source {
    content  = file("${path.module}/../../fraudflow/__init__.py")
    filename = "fraudflow/__init__.py"
  }
  source {
    content  = file("${path.module}/../../fraudflow/investigation.py")
    filename = "fraudflow/investigation.py"
  }
  source {
    content  = file("${path.module}/../../fraudflow/lambda_investigation.py")
    filename = "fraudflow/lambda_investigation.py"
  }
}

resource "aws_iam_role" "lambda_detection" {
  name = "${var.project_name}-detection-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy" "lambda_detection" {
  name = "${var.project_name}-detection-lambda-access"
  role = aws_iam_role.lambda_detection.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = [
          "${aws_cloudwatch_log_group.detection.arn}:*",
          "${aws_cloudwatch_log_group.detection.arn}:*:*",
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "kinesis:DescribeStream",
          "kinesis:DescribeStreamSummary",
          "kinesis:GetRecords",
          "kinesis:GetShardIterator",
          "kinesis:ListShards",
        ]
        Resource = [aws_kinesis_stream.transactions.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = "*"
        Condition = {
          StringEquals = {
            "kms:ViaService" = "kinesis.${var.aws_region}.amazonaws.com"
          }
        }
      },
      {
        Effect   = "Allow"
        Action   = ["sagemaker:InvokeEndpoint"]
        Resource = ["arn:aws:sagemaker:${var.aws_region}:${data.aws_caller_identity.current.account_id}:endpoint/${var.sagemaker_endpoint_name}"]
      },
      {
        Effect = "Allow"
        Action = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query"]
        Resource = [
          aws_dynamodb_table.transactions.arn,
          "${aws_dynamodb_table.transactions.arn}/index/*",
        ]
      },
      {
        Effect = "Allow"
        Action = ["sqs:SendMessage"]
        Resource = [
          aws_sqs_queue.investigation.arn,
          aws_sqs_queue.kinesis_failures.arn,
        ]
      },
    ]
  })
}

resource "aws_iam_role" "lambda_investigation" {
  name = "${var.project_name}-investigation-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy" "lambda_investigation" {
  name = "${var.project_name}-investigation-lambda-access"
  role = aws_iam_role.lambda_investigation.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = [
          "${aws_cloudwatch_log_group.investigation.arn}:*",
          "${aws_cloudwatch_log_group.investigation.arn}:*:*",
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:Query",
          "dynamodb:UpdateItem",
        ]
        Resource = [
          aws_dynamodb_table.transactions.arn,
          "${aws_dynamodb_table.transactions.arn}/index/*",
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "sqs:ChangeMessageVisibility",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:GetQueueUrl",
          "sqs:ReceiveMessage",
        ]
        Resource = [aws_sqs_queue.investigation.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel"]
        Resource = [local.bedrock_model_arn]
      },
    ]
  })
}

resource "aws_lambda_function" "detection" {
  function_name                  = "${var.project_name}-detection"
  role                           = aws_iam_role.lambda_detection.arn
  runtime                        = "python3.12"
  handler                        = "fraudflow.lambda_detection.handler"
  filename                       = data.archive_file.detection.output_path
  source_code_hash               = data.archive_file.detection.output_base64sha256
  timeout                        = 120
  memory_size                    = 512
  reserved_concurrent_executions = 2

  environment {
    variables = {
      FRAUDFLOW_TABLE_NAME         = aws_dynamodb_table.transactions.name
      FRAUDFLOW_SAGEMAKER_ENDPOINT = var.sagemaker_endpoint_name
      FRAUDFLOW_ALERT_QUEUE_URL    = aws_sqs_queue.investigation.url
      FRAUDFLOW_CUSTOMER_INDEX     = "customer-history-index"
    }
  }

  depends_on = [
    aws_iam_role_policy.lambda_detection,
    aws_sagemaker_endpoint.fraud,
  ]
  tags = local.common_tags
}

resource "aws_lambda_function" "investigation" {
  function_name                  = "${var.project_name}-investigation"
  role                           = aws_iam_role.lambda_investigation.arn
  runtime                        = "python3.12"
  handler                        = "fraudflow.lambda_investigation.handler"
  filename                       = data.archive_file.investigation.output_path
  source_code_hash               = data.archive_file.investigation.output_base64sha256
  timeout                        = 60
  memory_size                    = 256
  reserved_concurrent_executions = 2

  environment {
    variables = {
      FRAUDFLOW_TABLE_NAME       = aws_dynamodb_table.transactions.name
      FRAUDFLOW_CUSTOMER_INDEX   = "customer-history-index"
      FRAUDFLOW_BEDROCK_MODEL_ID = var.bedrock_model_id
      FRAUDFLOW_BEDROCK_REGION   = var.bedrock_region
    }
  }

  depends_on = [
    aws_iam_role_policy.lambda_investigation,
    aws_sagemaker_endpoint.fraud,
  ]
  tags = local.common_tags
}

resource "aws_lambda_event_source_mapping" "kinesis_detection" {
  count = var.enable_kinesis_processing ? 1 : 0

  event_source_arn                   = aws_kinesis_stream.transactions.arn
  function_name                      = aws_lambda_function.detection.arn
  starting_position                  = "TRIM_HORIZON"
  batch_size                         = 10
  maximum_batching_window_in_seconds = 1
  maximum_retry_attempts             = 3
  function_response_types            = ["ReportBatchItemFailures"]

  destination_config {
    on_failure {
      destination_arn = aws_sqs_queue.kinesis_failures.arn
    }
  }

  depends_on = [aws_iam_role_policy.lambda_detection]

  lifecycle {
    precondition {
      condition     = var.enable_sagemaker_endpoint
      error_message = "Enable the SageMaker endpoint before connecting the Kinesis detection Lambda."
    }
  }
}

resource "aws_lambda_event_source_mapping" "sqs_investigation" {
  count = var.enable_bedrock_investigation ? 1 : 0

  event_source_arn        = aws_sqs_queue.investigation.arn
  function_name           = aws_lambda_function.investigation.arn
  batch_size              = 1
  function_response_types = ["ReportBatchItemFailures"]

  depends_on = [aws_iam_role_policy.lambda_investigation]

  lifecycle {
    precondition {
      condition     = var.enable_sagemaker_endpoint
      error_message = "Enable the SageMaker endpoint before enabling Bedrock investigations."
    }
  }
}
