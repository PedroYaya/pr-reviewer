output "webhook_url" {
  description = "Set this as the GitHub App webhook URL (point a DNS name for the certificate at the ALB)"
  value       = "https://${aws_lb.gateway.dns_name}/webhook"
}

output "ecr_repository" {
  value = aws_ecr_repository.app.name
}

output "ecs_cluster" {
  value = aws_ecs_cluster.main.name
}

output "deploy_role_arn" {
  description = "GitHub Actions variable AWS_DEPLOY_ROLE_ARN"
  value       = aws_iam_role.deploy.arn
}

output "queue_url" {
  value = aws_sqs_queue.jobs.url
}

output "dead_letter_queue_url" {
  value = aws_sqs_queue.dead_letter.url
}

output "secret_ids" {
  description = "Fill these with put-secret-value before the first deploy"
  value       = { for k, s in aws_secretsmanager_secret.app : k => s.name }
}
