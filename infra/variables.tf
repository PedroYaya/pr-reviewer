variable "region" {
  type    = string
  default = "us-east-1"
}

variable "name" {
  description = "Prefix for every resource"
  type        = string
  default     = "pr-reviewer"
}

variable "vpc_id" {
  description = "Existing VPC; the private subnets need a NAT gateway to reach GitHub and OpenAI"
  type        = string
}

variable "public_subnet_ids" {
  description = "Subnets for the load balancer"
  type        = list(string)
}

variable "private_subnet_ids" {
  description = "Subnets for the ECS tasks and Redis"
  type        = list(string)
}

variable "certificate_arn" {
  description = "ACM certificate for the webhook endpoint"
  type        = string
}

variable "github_repository" {
  description = "owner/repo allowed to deploy through GitHub OIDC"
  type        = string
}

variable "github_app_id" {
  type = string
}

variable "image_tag" {
  description = "Initial image tag; later deploys come from GitHub Actions"
  type        = string
  default     = "latest"
}

variable "openai_model" {
  type    = string
  default = "gpt-4o"
}

variable "review_mode" {
  type    = string
  default = "auto"
}

variable "gateway_count" {
  type    = number
  default = 2
}

variable "reviewer_min_count" {
  type    = number
  default = 1
}

variable "reviewer_max_count" {
  type    = number
  default = 4
}

variable "alarm_email" {
  description = "Optional address subscribed to alarm notifications"
  type        = string
  default     = null
}

variable "create_github_oidc_provider" {
  description = "Set to false if the account already has the GitHub Actions OIDC provider"
  type        = bool
  default     = true
}
