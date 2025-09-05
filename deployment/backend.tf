terraform {
  backend "azurerm" {
    resource_group_name  = "aixcc"
    storage_account_name = "buttercuptf42cv"
    container_name       = "tfstate"
    key                  = "terraform.tfstate"
  }
}
