resource "aws_kinesis_stream" "transactions" {
  name             = "${var.project_name}-transactions"
  retention_period = 24

  stream_mode_details {
    stream_mode = "ON_DEMAND"
  }

  encryption_type = "KMS"
  kms_key_id      = "alias/aws/kinesis"
  tags            = local.common_tags
}

resource "aws_sqs_queue" "kinesis_failures" {
  name                      = "${var.project_name}-kinesis-failures"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
  tags                      = local.common_tags
}

resource "aws_sqs_queue" "investigation_dlq" {
  name                        = "${var.project_name}-investigation-dlq.fifo"
  fifo_queue                  = true
  content_based_deduplication = false
  message_retention_seconds   = 1209600
  sqs_managed_sse_enabled     = true
  tags                        = local.common_tags
}

resource "aws_sqs_queue" "investigation" {
  name                        = "${var.project_name}-investigation.fifo"
  fifo_queue                  = true
  content_based_deduplication = false
  message_retention_seconds   = 345600
  visibility_timeout_seconds  = 360
  sqs_managed_sse_enabled     = true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.investigation_dlq.arn
    maxReceiveCount     = 5
  })
  tags = local.common_tags
}
