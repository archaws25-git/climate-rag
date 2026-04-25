terraform {
  required_version = ">= 1.14.9"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.41.0"
    }
    awscc = {
      source  = "hashicorp/awscc"
      version = ">= 1.80.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.7"
    }    
  }
}

provider "aws" {
  region = var.aws_region
}

provider "awscc" {
  region = var.aws_region
}
