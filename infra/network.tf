resource "aws_security_group" "alb" {
  name        = "${var.name}-alb"
  description = "HTTPS from GitHub webhooks"
  vpc_id      = var.vpc_id

  ingress {
    description = "GitHub webhook deliveries; the HMAC signature is the real gate"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "gateway" {
  name        = "${var.name}-gateway"
  description = "Gateway tasks, reachable only from the load balancer"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "reviewer" {
  name        = "${var.name}-reviewer"
  description = "Reviewer tasks: outbound only (SQS, GitHub, OpenAI, Redis)"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "redis" {
  name        = "${var.name}-redis"
  description = "Redis, reachable only from reviewer tasks"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.reviewer.id]
  }
}
