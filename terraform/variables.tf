variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name used for resource naming"
  type        = string
  default     = "climate-rag"
}

variable "memory_event_expiry_days" {
  description = "Days after which memory events expire"
  type        = number
  default     = 30
}

variable "tags" {
  description = "Tags for all resources"
  type        = map(string)
  default = {
    Project     = "ClimateRAG"
    Environment = "demo"
    ManagedBy   = "terraform"
  }
}
