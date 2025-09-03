#resource for random prefixes, helps with unique names and identifiers
resource "random_pet" "ssh_key_name" {
  prefix    = "ssh"
  separator = ""
}
#azapi_resource_action resource is used to perform specific actions on an Azure resource, such as starting or stopping a virtual machine. Here we're generating ssh keys
resource "azapi_resource_action" "ssh_public_key_gen" {
  type        = "Microsoft.Compute/sshPublicKeys@2022-11-01"
  resource_id = azapi_resource.ssh_public_key.id
  action      = "generateKeyPair"
  method      = "POST"

  response_export_values = ["publicKey", "privateKey"]
}

resource "azapi_resource" "ssh_public_key" {
  type      = "Microsoft.Compute/sshPublicKeys@2022-11-01"
  name      = random_pet.ssh_key_name.id
  location  = local.resource_group_location
  parent_id = local.resource_group_id
}

output "key_data" {
  value = azapi_resource_action.ssh_public_key_gen.output.publicKey
}


# Generate random resource group name
resource "random_pet" "rg_name" {
  prefix = var.resource_group_name_prefix
}

# Data source to reference existing resource group if provided
data "azurerm_resource_group" "existing" {
  count = var.resource_group_name != null ? 1 : 0
  name  = var.resource_group_name
}

# Create new resource group only if resource_group_name is not provided
resource "azurerm_resource_group" "rg" {
  count    = var.resource_group_name == null ? 1 : 0
  #ts:skip=AC_AZURE_0389 Locks not required
  location = var.resource_group_location
  name     = random_pet.rg_name.id
}

# Local values to reference the appropriate resource group
locals {
  resource_group_name = var.resource_group_name != null ? var.resource_group_name : azurerm_resource_group.rg[0].name
  resource_group_location = var.resource_group_name != null ? data.azurerm_resource_group.existing[0].location : azurerm_resource_group.rg[0].location
  resource_group_id = var.resource_group_name != null ? data.azurerm_resource_group.existing[0].id : azurerm_resource_group.rg[0].id
}

# Optional: Adds resource lock to prevent deletion of the RG. Requires additional configuration
#resource "azurerm_management_lock" "resource-group-level" {
#  name       = "resource-group-cannotdelete-lock"
#  scope      = local.resource_group_id
#  lock_level = "CanNotDelete"
#  notes      = "This Resource Group is set to CanNotDelete to prevent accidental deletion."
#}


resource "random_pet" "azurerm_kubernetes_cluster_name" {
  prefix = "cluster"
}

resource "random_pet" "azurerm_kubernetes_cluster_dns_prefix" {
  prefix = "dns"
}

resource "azurerm_kubernetes_cluster" "primary" {
  location            = local.resource_group_location
  name                = random_pet.azurerm_kubernetes_cluster_name.id
  resource_group_name = local.resource_group_name
  dns_prefix          = random_pet.azurerm_kubernetes_cluster_dns_prefix.id
  sku_tier            = "Standard"
  # Disable automatic upgrades to prevent disruption
  node_os_upgrade_channel = "None"

  identity {
    type = "SystemAssigned"
  }

  default_node_pool {
    name                         = "sys"
    vm_size                      = var.vm_size
    max_pods                     = 100
    temporary_name_for_rotation  = "tempnodepool"
    only_critical_addons_enabled = true
    node_count                   = var.sys_node_count
    upgrade_settings {
      max_surge = "10%"
    }
  }

  linux_profile {
    admin_username = var.username

    ssh_key {
      key_data = azapi_resource_action.ssh_public_key_gen.output.publicKey
    }
  }
  network_profile {
    network_plugin    = "azure"
    network_policy    = "azure"
    load_balancer_sku = "standard"
  }
  oms_agent {
    log_analytics_workspace_id      = azurerm_log_analytics_workspace.aks_logs.id
    msi_auth_for_monitoring_enabled = true
  }
}

resource "azurerm_kubernetes_cluster_node_pool" "user" {
  name                  = "usr"
  mode                  = "User"
  kubernetes_cluster_id = azurerm_kubernetes_cluster.primary.id
  vm_size               = var.vm_size
  max_pods              = 100
  node_count            = var.usr_node_count
  upgrade_settings {
    max_surge = "10%"
  }
}

#Monitoring Log Anayltics
resource "azurerm_log_analytics_workspace" "aks_logs" {
  name                = "${local.resource_group_name}-logs"
  location            = local.resource_group_location
  resource_group_name = local.resource_group_name
  sku                 = "PerGB2018"
  retention_in_days   = 30
}
