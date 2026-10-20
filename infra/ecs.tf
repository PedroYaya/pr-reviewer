resource "aws_ecs_cluster" "main" {
  name = var.name

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${var.name}"
  retention_in_days = 30
}

# Prometheus metrics converted to CloudWatch metrics (embedded metric format).
resource "aws_cloudwatch_log_group" "metrics" {
  name              = "/ecs/${var.name}/metrics"
  retention_in_days = 7
}

locals {
  image = "${aws_ecr_repository.app.repository_url}:${var.image_tag}"

  common_env = [
    { name = "QUEUE_BACKEND", value = "sqs" },
    { name = "SQS_QUEUE_URL", value = aws_sqs_queue.jobs.url },
    { name = "SQS_DEAD_LETTER_QUEUE_URL", value = aws_sqs_queue.dead_letter.url },
    { name = "AWS_REGION", value = var.region },
    { name = "LOG_FORMAT", value = "json" },
    { name = "OTEL_EXPORTER_OTLP_ENDPOINT", value = "http://localhost:4318" },
  ]

  # ADOT collector sidecar: receives OTLP traces for X-Ray and scrapes the
  # app's /metrics into CloudWatch. Only the metrics listed here are kept.
  collector_config = {
    for service, port in { gateway = 8000, reviewer = 8001 } : service => yamlencode({
      receivers = {
        otlp = { protocols = { http = { endpoint = "0.0.0.0:4318" } } }
        prometheus = {
          config = {
            scrape_configs = [{
              job_name        = service
              scrape_interval = "30s"
              static_configs  = [{ targets = ["localhost:${port}"] }]
            }]
          }
        }
      }
      processors = { batch = {} }
      exporters = {
        awsxray = {}
        awsemf = {
          namespace               = "PRReviewer"
          log_group_name          = aws_cloudwatch_log_group.metrics.name
          dimension_rollup_option = "NoDimensionRollup"
          metric_declarations = [
            { dimensions = [["kind", "outcome"]], metric_name_selectors = ["^prr_review_jobs_total$"] },
            { dimensions = [["type"]], metric_name_selectors = ["^prr_llm_tokens_total$"] },
            { dimensions = [["service", "reason"]], metric_name_selectors = ["^prr_http_retries_total$"] },
            { dimensions = [["event", "outcome"]], metric_name_selectors = ["^prr_webhooks_total$"] },
            { dimensions = [["severity"]], metric_name_selectors = ["^prr_findings_total$"] },
            { dimensions = [["reason"]], metric_name_selectors = ["^prr_guardrail_dropped_findings_total$"] },
          ]
        }
      }
      service = {
        pipelines = {
          traces  = { receivers = ["otlp"], processors = ["batch"], exporters = ["awsxray"] }
          metrics = { receivers = ["prometheus"], processors = ["batch"], exporters = ["awsemf"] }
        }
      }
    })
  }
}

locals {
  containers = {
    gateway = {
      port    = 8000
      env     = [{ name = "SERVICE", value = "gateway" }, { name = "PORT", value = "8000" }]
      secrets = [{ name = "GITHUB_WEBHOOK_SECRET", valueFrom = aws_secretsmanager_secret.app["webhook_secret"].arn }]
    }
    reviewer = {
      port = 8001
      env = [
        { name = "SERVICE", value = "reviewer" },
        { name = "PORT", value = "8001" },
        { name = "GITHUB_APP_ID", value = var.github_app_id },
        { name = "OPENAI_MODEL", value = var.openai_model },
        { name = "REVIEW_MODE", value = var.review_mode },
        { name = "REDIS_URL", value = "rediss://${aws_elasticache_replication_group.redis.primary_endpoint_address}:6379/0" },
      ]
      secrets = [
        { name = "GITHUB_PRIVATE_KEY", valueFrom = aws_secretsmanager_secret.app["github_private_key"].arn },
        { name = "OPENAI_API_KEY", valueFrom = aws_secretsmanager_secret.app["openai_api_key"].arn },
      ]
    }
  }
}

resource "aws_ecs_task_definition" "service" {
  for_each = local.containers

  family                   = "${var.name}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = each.key == "reviewer" ? 512 : 256
  memory                   = each.key == "reviewer" ? 1024 : 512
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = each.key == "reviewer" ? aws_iam_role.reviewer.arn : aws_iam_role.gateway.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name         = "app"
      image        = local.image
      essential    = true
      portMappings = [{ containerPort = each.value.port, protocol = "tcp" }]
      environment  = concat(local.common_env, each.value.env)
      secrets      = each.value.secrets
      # SIGTERM lets the worker finish the review in progress (SHUTDOWN_GRACE_SECONDS=100).
      stopTimeout = 120
      healthCheck = {
        command     = ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${each.value.port}/health', timeout=3)"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 20
      }
      dependsOn = [{ containerName = "otel-collector", condition = "START" }]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.app.name
          awslogs-region        = var.region
          awslogs-stream-prefix = each.key
        }
      }
    },
    {
      name        = "otel-collector"
      image       = "public.ecr.aws/aws-observability/aws-otel-collector:v0.43.1"
      essential   = false
      environment = [{ name = "AOT_CONFIG_CONTENT", value = local.collector_config[each.key] }]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.app.name
          awslogs-region        = var.region
          awslogs-stream-prefix = "${each.key}-otel"
        }
      }
    },
  ])
}

resource "aws_ecs_service" "gateway" {
  name                              = "${var.name}-gateway"
  cluster                           = aws_ecs_cluster.main.id
  task_definition                   = aws_ecs_task_definition.service["gateway"].arn
  desired_count                     = var.gateway_count
  launch_type                       = "FARGATE"
  health_check_grace_period_seconds = 30

  network_configuration {
    subnets         = var.private_subnet_ids
    security_groups = [aws_security_group.gateway.id]
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.gateway.arn
    container_name   = "app"
    container_port   = 8000
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  # GitHub Actions deploys new task definition revisions.
  lifecycle {
    ignore_changes = [task_definition]
  }

  depends_on = [aws_lb_listener.https]
}

resource "aws_ecs_service" "reviewer" {
  name            = "${var.name}-reviewer"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.service["reviewer"].arn
  desired_count   = var.reviewer_min_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets         = var.private_subnet_ids
    security_groups = [aws_security_group.reviewer.id]
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  # Autoscaling owns desired_count; GitHub Actions owns the task definition.
  lifecycle {
    ignore_changes = [task_definition, desired_count]
  }
}

# Add workers when reviews pile up in the queue.
resource "aws_appautoscaling_target" "reviewer" {
  service_namespace  = "ecs"
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.reviewer.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  min_capacity       = var.reviewer_min_count
  max_capacity       = var.reviewer_max_count
}

resource "aws_appautoscaling_policy" "reviewer_queue_depth" {
  name               = "${var.name}-reviewer-queue-depth"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.reviewer.service_namespace
  resource_id        = aws_appautoscaling_target.reviewer.resource_id
  scalable_dimension = aws_appautoscaling_target.reviewer.scalable_dimension

  target_tracking_scaling_policy_configuration {
    target_value       = 3
    scale_in_cooldown  = 300
    scale_out_cooldown = 60

    customized_metric_specification {
      namespace   = "AWS/SQS"
      metric_name = "ApproximateNumberOfMessagesVisible"
      statistic   = "Average"
      dimensions {
        name  = "QueueName"
        value = aws_sqs_queue.jobs.name
      }
    }
  }
}
