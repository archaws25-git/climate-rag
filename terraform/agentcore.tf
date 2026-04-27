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
    #tf_script    = "${replace(path.module, "\\", "/")}/../infra/tf_agentcore.py"
    tf_script = "${path.module}/../../infra/tf_agentcore.py"
    tf_out_dir   = replace(path.module, "\\", "/")
  }

  provisioner "local-exec" {
    when    = create
    command = "python3 \"${self.triggers.tf_script}\" create_memory --region ${self.triggers.region} --name ClimateRAGMemoryTF --out \"${self.triggers.tf_out_dir}/memory_id.txt\""
  }

  provisioner "local-exec" {
    when    = destroy
    command = "python3 \"${self.triggers.tf_script}\" delete_memory --region ${self.triggers.region} --id-file \"${self.triggers.tf_out_dir}/memory_id.txt\""
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
   # tf_script    = "${replace(path.module, "\\", "/")}/../infra/tf_agentcore.py"
    tf_script = "${path.module}/../../infra/tf_agentcore.py"
    tf_out_dir   = replace(path.module, "\\", "/")
  }

  provisioner "local-exec" {
    when    = create
    command = "python3 \"${self.triggers.tf_script}\" create_code_interpreter --region ${self.triggers.region} --name ClimateChartInterpreterTF --out \"${self.triggers.tf_out_dir}/code_interpreter_id.txt\""
  }

  provisioner "local-exec" {
    when    = destroy
    command = "python3 \"${self.triggers.tf_script}\" delete_code_interpreter --region ${self.triggers.region} --id-file \"${self.triggers.tf_out_dir}/code_interpreter_id.txt\""
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
    #tf_script        = "${replace(path.module, "\\", "/")}/../infra/tf_agentcore.py"
    tf_script = "${path.module}/../../infra/tf_agentcore.py"
    tf_out_dir       = replace(path.module, "\\", "/")
    gateway_role_arn = aws_iam_role.gateway.arn
    nasa_lambda_arn  = aws_lambda_function.nasa_power.arn
    noaa_lambda_arn  = aws_lambda_function.noaa_ncei.arn
  }

  provisioner "local-exec" {
    when    = create
    command =<<EOT
python3 "${self.triggers.tf_script}" create_gateway \
  --region ${self.triggers.region} \
  --name ClimateDataGatewayTF \
  --role-arn "${self.triggers.gateway_role_arn}" \
  --nasa-arn "${self.triggers.nasa_lambda_arn}" \
  --noaa-arn "${self.triggers.noaa_lambda_arn}" \
  --out "${self.triggers.tf_out_dir}/gateway_id.txt"
EOT
  }

  provisioner "local-exec" {
    when    = destroy
    command = "python3 \"${self.triggers.tf_script}\" delete_gateway --region ${self.triggers.region} --id-file \"${self.triggers.tf_out_dir}/gateway_id.txt\""
  }
}

data "local_file" "gateway_id" {
  filename   = "${path.module}/gateway_id.txt"
  depends_on = [null_resource.gateway]
}
