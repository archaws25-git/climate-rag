# ─── IAM Role for AgentCore Gateway ──────────────────────────────

resource "aws_iam_role" "gateway" {
  name = "${var.project_name}-gateway-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "bedrock-agentcore.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = var.tags
}

resource "aws_iam_role_policy" "gateway_invoke_lambda" {
  name = "invoke-lambda"
  role = aws_iam_role.gateway.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = [
        aws_lambda_function.nasa_power.arn,
        aws_lambda_function.noaa_ncei.arn,
      ]
    }]
  })
}

# ─── AgentCore Memory ────────────────────────────────────────────

resource "null_resource" "memory" {
  triggers = {
    region       = var.aws_region
    project_name = var.project_name
  }

  provisioner "local-exec" {
    when        = create
    interpreter = ["python3", "${path.module}/../infra/tf_agentcore.py"]
    command     = "create_memory --region ${var.aws_region} --name ClimateRAGMemoryTF --out ${path.module}/memory_id.txt"
  }

  provisioner "local-exec" {
    when        = destroy
    interpreter = ["python3", "${path.module}/../infra/tf_agentcore.py"]
    command     = "delete_memory --region ${self.triggers.region} --id-file ${path.module}/memory_id.txt"
  }
}

data "local_file" "memory_id" {
  filename   = "${path.module}/memory_id.txt"
  depends_on = [null_resource.memory]
}

# ─── AgentCore Code Interpreter ──────────────────────────────────

resource "null_resource" "code_interpreter" {
  triggers = {
    region       = var.aws_region
    project_name = var.project_name
  }

  provisioner "local-exec" {
    when        = create
    interpreter = ["python3", "${path.module}/../infra/tf_agentcore.py"]
    command     = "create_code_interpreter --region ${var.aws_region} --name ClimateChartInterpreterTF --out ${path.module}/code_interpreter_id.txt"
  }

  provisioner "local-exec" {
    when        = destroy
    interpreter = ["python3", "${path.module}/../infra/tf_agentcore.py"]
    command     = "delete_code_interpreter --region ${self.triggers.region} --id-file ${path.module}/code_interpreter_id.txt"
  }
}

data "local_file" "code_interpreter_id" {
  filename   = "${path.module}/code_interpreter_id.txt"
  depends_on = [null_resource.code_interpreter]
}

# ─── AgentCore Gateway + Targets ─────────────────────────────────

resource "null_resource" "gateway" {
  depends_on = [aws_iam_role.gateway, aws_iam_role_policy.gateway_invoke_lambda]

  triggers = {
    region           = var.aws_region
    project_name     = var.project_name
    gateway_role_arn = aws_iam_role.gateway.arn
    nasa_lambda_arn  = aws_lambda_function.nasa_power.arn
    noaa_lambda_arn  = aws_lambda_function.noaa_ncei.arn
  }

  provisioner "local-exec" {
    when        = create
    interpreter = ["python3", "${path.module}/../infra/tf_agentcore.py"]
    command     = "create_gateway --region ${var.aws_region} --name ClimateDataGatewayTF --role-arn ${aws_iam_role.gateway.arn} --nasa-arn ${aws_lambda_function.nasa_power.arn} --noaa-arn ${aws_lambda_function.noaa_ncei.arn} --out ${path.module}/gateway_id.txt"
  }

  provisioner "local-exec" {
    when        = destroy
    interpreter = ["python3", "${path.module}/../infra/tf_agentcore.py"]
    command     = "delete_gateway --region ${self.triggers.region} --id-file ${path.module}/gateway_id.txt"
  }
}

data "local_file" "gateway_id" {
  filename   = "${path.module}/gateway_id.txt"
  depends_on = [null_resource.gateway]
}
