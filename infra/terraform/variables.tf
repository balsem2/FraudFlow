variable "aws_region" {
  description = "AWS home region for this account."
  type        = string
  default     = "eu-north-1"
}

variable "project_name" {
  description = "Lowercase project prefix used for AWS resource names."
  type        = string
  default     = "fraudflow"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,19}$", var.project_name))
    error_message = "project_name must be 3-20 lowercase letters, digits, or hyphens, and start with a letter."
  }
}

variable "bedrock_region" {
  description = "Region where the selected Bedrock model is available and enabled."
  type        = string
  default     = "eu-north-1"
}

variable "bedrock_model_id" {
  description = "Bedrock foundation-model ID used for alert investigations."
  type        = string
  default     = "amazon.nova-lite-v1:0"
}

variable "bedrock_model_arn" {
  description = "Optional full Bedrock model/profile ARN for least-privilege invocation permissions."
  type        = string
  default     = ""
}

variable "inference_image_tag" {
  description = "Immutable tag already pushed to the inference ECR repository before enabling SageMaker."
  type        = string
  default     = "v1"
}

variable "dashboard_image_tag" {
  description = "Immutable tag already pushed to the dashboard ECR repository before enabling ECS."
  type        = string
  default     = "v1"
}

variable "sagemaker_endpoint_name" {
  description = "SageMaker endpoint name consumed by Lambda and the dashboard."
  type        = string
  default     = "fraudflow-xgb"
}

variable "sagemaker_instance_type" {
  description = "Always-on SageMaker endpoint instance type; review cost before enabling."
  type        = string
  default     = "ml.m5.large"
}

variable "enable_sagemaker_endpoint" {
  description = "Create the billable SageMaker endpoint after the image and model are available."
  type        = bool
  default     = false
}

variable "enable_kinesis_processing" {
  description = "Attach the detection Lambda to Kinesis after the SageMaker endpoint is ready."
  type        = bool
  default     = false
}

variable "enable_bedrock_investigation" {
  description = "Consume alert messages and invoke Bedrock only after model access and permissions are verified."
  type        = bool
  default     = false
}

variable "enable_dashboard_service" {
  description = "Run the public-subnet ECS dashboard after its image is pushed."
  type        = bool
  default     = false
}

variable "dashboard_allowed_cidr" {
  description = "Only this IPv4 CIDR can access dashboard port 8501. Set it to your public IP/32."
  type        = string
  default     = "127.0.0.1/32"

  validation {
    condition     = can(cidrnetmask(var.dashboard_allowed_cidr)) && can(regex("/32$", var.dashboard_allowed_cidr))
    error_message = "dashboard_allowed_cidr must be one valid IPv4 address in /32 form."
  }
}

variable "vpc_cidr" {
  description = "Private address range for the small public-subnet demo VPC."
  type        = string
  default     = "10.40.0.0/16"
}
