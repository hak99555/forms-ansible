provider "oci" {
  region              = var.region
  auth                = var.auth
  config_file_profile = var.config_file_profile
}

provider "oci" {
  alias               = "home"
  region              = var.home_region
  auth                = var.auth
  config_file_profile = var.config_file_profile
}
