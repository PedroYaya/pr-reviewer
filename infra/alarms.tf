resource "aws_sns_topic" "alarms" {
  name = "${var.name}-alarms"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alarm_email == null ? 0 : 1
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

resource "aws_cloudwatch_metric_alarm" "dead_letters" {
  alarm_name          = "${var.name}-dead-letters"
  alarm_description   = "Review jobs failed for good. Inspect the DLQ, fix, then redrive."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.dead_letter.name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "queue_age" {
  alarm_name          = "${var.name}-queue-backlog"
  alarm_description   = "Oldest review job has waited over 10 minutes; workers are stuck or under-scaled."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateAgeOfOldestMessage"
  dimensions          = { QueueName = aws_sqs_queue.jobs.name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 2
  threshold           = 600
  comparison_operator = "GreaterThanThreshold"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

# Successful run rate = success / (success + dead_letter), from the app's own metrics.
resource "aws_cloudwatch_metric_alarm" "success_rate" {
  alarm_name          = "${var.name}-success-rate"
  alarm_description   = "Less than 90% of finished review jobs succeeded over the last 3 hours."
  evaluation_periods  = 1
  threshold           = 0.9
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]

  metric_query {
    id          = "rate"
    expression  = "IF(success + failed > 0, success / (success + failed), 1)"
    label       = "Successful run rate"
    return_data = true
  }

  dynamic "metric_query" {
    for_each = { success = "success", failed = "dead_letter" }
    content {
      id = metric_query.key
      metric {
        namespace   = "PRReviewer"
        metric_name = "prr_review_jobs_total"
        dimensions  = { kind = "review", outcome = metric_query.value }
        stat        = "Sum"
        period      = 10800
      }
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "gateway_5xx" {
  alarm_name          = "${var.name}-gateway-5xx"
  alarm_description   = "Webhook endpoint is failing; GitHub will mark deliveries as failed."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_Target_5XX_Count"
  dimensions          = { LoadBalancer = aws_lb.gateway.arn_suffix, TargetGroup = aws_lb_target_group.gateway.arn_suffix }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 5
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}
