data "aws_caller_identity" "current" {}

# ─── S3 Bucket for FAISS Index ───────────────────────────────────

resource "aws_s3_bucket" "index" {
  bucket        = "${var.project_name}-index-${data.aws_caller_identity.current.account_id}"
  force_destroy = true
  tags          = var.tags
}

resource "aws_s3_bucket_server_side_encryption_configuration" "index" {
  bucket = aws_s3_bucket.index.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "index" {
  bucket                  = aws_s3_bucket.index.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ─── IAM Role for Lambda Proxies ─────────────────────────────────

resource "aws_iam_role" "lambda" {
  name = "${var.project_name}-lambda-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# ─── Lambda: NASA POWER Proxy ────────────────────────────────────

data "archive_file" "nasa_power" {
  type        = "zip"
  source_file = "${path.module}/../gateway/lambda_nasa_power/handler.py"
  output_path = "${path.module}/.build/nasa_power.zip"
}

resource "aws_lambda_function" "nasa_power" {
  function_name    = "${var.project_name}-nasa-power"
  role             = aws_iam_role.lambda.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  timeout          = 30
  filename         = data.archive_file.nasa_power.output_path
  source_code_hash = data.archive_file.nasa_power.output_base64sha256
  tags             = var.tags
}

# ─── Lambda: NOAA NCEI Proxy ────────────────────────────────────

data "archive_file" "noaa_ncei" {
  type        = "zip"
  source_file = "${path.module}/../gateway/lambda_noaa_ncei/handler.py"
  output_path = "${path.module}/.build/noaa_ncei.zip"
}

resource "aws_lambda_function" "noaa_ncei" {
  function_name    = "${var.project_name}-noaa-ncei"
  role             = aws_iam_role.lambda.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  timeout          = 30
  filename         = data.archive_file.noaa_ncei.output_path
  source_code_hash = data.archive_file.noaa_ncei.output_base64sha256
  tags             = var.tags
}
