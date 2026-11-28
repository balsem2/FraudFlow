data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "dashboard" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = merge(local.common_tags, { Name = "${var.project_name}-vpc" })
}

resource "aws_internet_gateway" "dashboard" {
  vpc_id = aws_vpc.dashboard.id
  tags   = local.common_tags
}

resource "aws_subnet" "dashboard_public" {
  count = 2

  vpc_id                  = aws_vpc.dashboard.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index + 1)
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true

  tags = merge(local.common_tags, { Name = "${var.project_name}-public-${count.index + 1}" })
}

resource "aws_route_table" "dashboard_public" {
  vpc_id = aws_vpc.dashboard.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.dashboard.id
  }

  tags = local.common_tags
}

resource "aws_route_table_association" "dashboard_public" {
  count = 2

  subnet_id      = aws_subnet.dashboard_public[count.index].id
  route_table_id = aws_route_table.dashboard_public.id
}

resource "aws_security_group" "dashboard" {
  name        = "${var.project_name}-dashboard"
  description = "Restrict the demo dashboard to the configured client CIDR."
  vpc_id      = aws_vpc.dashboard.id

  ingress {
    description = "Streamlit dashboard; set dashboard_allowed_cidr to your own public IP/32."
    from_port   = 8501
    to_port     = 8501
    protocol    = "tcp"
    cidr_blocks = [var.dashboard_allowed_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.common_tags
}

resource "aws_ecs_cluster" "dashboard" {
  name = "${var.project_name}-cluster"
  tags = local.common_tags
}

resource "aws_iam_role" "ecs_execution" {
  name = "${var.project_name}-ecs-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "ecs_execution" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "ecs_dashboard" {
  name = "${var.project_name}-dashboard-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy" "ecs_dashboard" {
  name = "${var.project_name}-dashboard-access"
  role = aws_iam_role.ecs_dashboard.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query"]
        Resource = [
          aws_dynamodb_table.transactions.arn,
          "${aws_dynamodb_table.transactions.arn}/index/*",
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["sagemaker:InvokeEndpoint"]
        Resource = ["arn:aws:sagemaker:${var.aws_region}:${data.aws_caller_identity.current.account_id}:endpoint/${var.sagemaker_endpoint_name}"]
      },
      {
        Effect   = "Allow"
        Action   = ["sqs:SendMessage"]
        Resource = [aws_sqs_queue.investigation.arn]
      },
    ]
  })
}

resource "aws_ecs_task_definition" "dashboard" {
  family                   = "${var.project_name}-dashboard"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_dashboard.arn

  container_definitions = jsonencode([{
    name      = "dashboard"
    image     = "${aws_ecr_repository.dashboard.repository_url}:${var.dashboard_image_tag}"
    essential = true
    portMappings = [{
      containerPort = 8501
      hostPort      = 8501
      protocol      = "tcp"
    }]
    environment = [
      { name = "FRAUDFLOW_BACKEND", value = "aws" },
      { name = "FRAUDFLOW_TABLE_NAME", value = aws_dynamodb_table.transactions.name },
      { name = "FRAUDFLOW_RECENT_INDEX", value = "recent-index" },
      { name = "FRAUDFLOW_CUSTOMER_INDEX", value = "customer-history-index" },
      { name = "FRAUDFLOW_SAGEMAKER_ENDPOINT", value = var.sagemaker_endpoint_name },
      { name = "FRAUDFLOW_ALERT_QUEUE_URL", value = aws_sqs_queue.investigation.url },
      { name = "AWS_REGION", value = var.aws_region },
    ]
    healthCheck = {
      command     = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4)\""]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 60
    }
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.dashboard.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "dashboard"
      }
    }
  }])

  tags = local.common_tags
}

resource "aws_ecs_service" "dashboard" {
  count = var.enable_dashboard_service ? 1 : 0

  name            = "${var.project_name}-dashboard"
  cluster         = aws_ecs_cluster.dashboard.id
  task_definition = aws_ecs_task_definition.dashboard.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.dashboard_public[*].id
    security_groups  = [aws_security_group.dashboard.id]
    assign_public_ip = true
  }

  health_check_grace_period_seconds = 90
  depends_on = [
    aws_iam_role_policy_attachment.ecs_execution,
    aws_iam_role_policy.ecs_dashboard,
    aws_sagemaker_endpoint.fraud,
  ]
  tags = local.common_tags

  lifecycle {
    precondition {
      condition     = var.enable_sagemaker_endpoint
      error_message = "Enable the SageMaker endpoint before enabling the AWS dashboard."
    }
  }
}
