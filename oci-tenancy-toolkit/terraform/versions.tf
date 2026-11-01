terraform {
  required_version = ">= 1.6, < 2.0"
  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "~> 9.11.0"
    }
  }
  backend "local" {}
}
