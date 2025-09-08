terraform {
  backend "azurerm" {
    resource_group_name  = "example-tfstate-rg"
    storage_account_name = "tffinalacc"
    container_name       = "tfstate"
    key                  = "terraform.tfstate"
  }
}
