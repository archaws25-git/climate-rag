output "s3_bucket_name" {
  description = "S3 bucket for FAISS index"
  value       = aws_s3_bucket.index.id
}

output "memory_id" {
  description = "AgentCore Memory ID"
  value       = trimspace(data.local_file.memory_id.content)
}

output "code_interpreter_id" {
  description = "AgentCore Code Interpreter ID"
  value       = trimspace(data.local_file.code_interpreter_id.content)
}

output "gateway_id" {
  description = "AgentCore Gateway ID"
  value       = trimspace(data.local_file.gateway_id.content)
}

output "nasa_power_lambda_arn" {
  description = "NASA POWER Lambda ARN"
  value       = aws_lambda_function.nasa_power.arn
}

output "noaa_ncei_lambda_arn" {
  description = "NOAA NCEI Lambda ARN"
  value       = aws_lambda_function.noaa_ncei.arn
}

output "environment_variables" {
  description = "PowerShell env vars to set before running Streamlit"
  value = join("\n", [
    "$env:AWS_REGION = \"${var.aws_region}\"",
    "$env:CLIMATE_RAG_BUCKET = \"${aws_s3_bucket.index.id}\"",
    "$env:CLIMATE_RAG_MEMORY_ID = \"${trimspace(data.local_file.memory_id.content)}\"",
    "$env:CLIMATE_RAG_CODE_INTERPRETER_ID = \"${trimspace(data.local_file.code_interpreter_id.content)}\"",
  ])
}
