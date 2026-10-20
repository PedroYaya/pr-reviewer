# Values are set outside Terraform (console or CLI) so they never reach state:
#   aws secretsmanager put-secret-value --secret-id pr-reviewer/openai-api-key --secret-string ...

locals {
  secrets = {
    webhook_secret     = "github-webhook-secret"
    github_private_key = "github-private-key"
    openai_api_key     = "openai-api-key"
  }
}

resource "aws_secretsmanager_secret" "app" {
  for_each = local.secrets
  name     = "${var.name}/${each.value}"
}
