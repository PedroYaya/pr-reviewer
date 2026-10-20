# Review jobs. A message stays invisible while a worker reviews it and is
# deleted when the job finishes; if the worker dies, SQS delivers it again.
# After 3 such deliveries the redrive policy moves it to the DLQ. Jobs that
# fail with an error are retried and dead-lettered by the worker itself.

resource "aws_sqs_queue" "dead_letter" {
  name                      = "${var.name}-jobs-dlq"
  message_retention_seconds = 14 * 24 * 3600
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "jobs" {
  name                       = "${var.name}-jobs"
  visibility_timeout_seconds = 900 # longer than the slowest review
  message_retention_seconds  = 4 * 24 * 3600
  receive_wait_time_seconds  = 20
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dead_letter.arn
    maxReceiveCount     = 3
  })
}

resource "aws_sqs_queue_redrive_allow_policy" "dead_letter" {
  queue_url = aws_sqs_queue.dead_letter.id
  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.jobs.arn]
  })
}
