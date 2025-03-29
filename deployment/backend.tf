terraform {
  backend "azurerm" {
    resource_group_name  = "tfstate-rg"
    storage_account_name = "tfstateserviceact" # "tfstateserviceactprod"
    container_name       = "tfstate"
    key                  = "terraform.tfstate"
  }
}
