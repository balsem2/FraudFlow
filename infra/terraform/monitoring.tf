resource "aws_cloudwatch_log_group" "detection" {
  name              = "/aws/lambda/${var.project_name}-detection"
  retention_in_days = 14
  tags              = local.common_tags
}

resource "aws_cloudwatch_log_group" "investigation" {
  name              = "/aws/lambda/${var.project_name}-investigation"
  retention_in_days = 14
  tags              = local.common_tags
}

resource "aws_cloudwatch_log_group" "dashboard" {
  name              = "/ecs/${var.project_name}/dashboard"
  retention_in_days = 14
  tags              = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "detection_errors" {
  alarm_name          = "${var.project_name}-detection-errors"
  alarm_description   = "Detection Lambda reported one or more errors."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.detection.function_name
  }

  tags = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "investigation_errors" {
  alarm_name          = "${var.project_name}-investigation-errors"
  alarm_description   = "Investigation Lambda reported one or more errors."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.investigation.function_name
  }

  tags = local.common_tags
}
