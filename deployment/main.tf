terraform {
  required_version = ">=1.0"

  required_providers {
    azapi = {
      source  = "azure/azapi"
      version = "2.0.1"
    }
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "4.7.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "3.6.3"
    }
    time = {
      source  = "hashicorp/time"
      version = "0.12.1"
    }
  }
}


provider "azurerm" {
  features {}
  #Can setup your service principal here, currently commented out to use az cli apply terraform
  #subscription_id   = "<azure_subscription_id>"
  #tenant_id         = "<azure_subscription_tenant_id>"
  #client_id         = "<service_principal_appid>"
  #client_secret     = "<service_principal_password>"
}

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
  location  = azurerm_resource_group.rg.location
  parent_id = azurerm_resource_group.rg.id
}

output "key_data" {
  value = azapi_resource_action.ssh_public_key_gen.output.publicKey
}


# Generate random resource group name
resource "random_pet" "rg_name" {
  prefix = var.resource_group_name_prefix
}

resource "azurerm_resource_group" "rg" {
  #ts:skip=AC_AZURE_0389 Locks not required
  location = var.resource_group_location
  name     = random_pet.rg_name.id
}

# Optional: Adds resource lock to prevent deletion of the RG. Requires additional configuration
#resource "azurerm_management_lock" "resource-group-level" {
#  name       = "resource-group-cannotdelete-lock"
#  scope      = azurerm_resource_group.rg.id
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
  location            = azurerm_resource_group.rg.location
  name                = random_pet.azurerm_kubernetes_cluster_name.id
  resource_group_name = azurerm_resource_group.rg.name
  dns_prefix          = random_pet.azurerm_kubernetes_cluster_dns_prefix.id

  identity {
    type = "SystemAssigned"
  }

  default_node_pool {
    name                         = "sys"
    vm_size                      = "Standard_D5_v2"
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
    network_plugin = "azure"
    network_policy = "azure"
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
  vm_size               = "Standard_D5_v2"
  max_pods              = 100
  node_count            = var.usr_node_count
  upgrade_settings {
    max_surge = "10%"
  }
}

#Monitoring Log Anayltics
resource "azurerm_log_analytics_workspace" "aks_logs" {
  name                = "${random_pet.rg_name.id}-logs"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

#
# Kubernetes Resources
#

data "azurerm_kubernetes_cluster" "primary" {
  name                = azurerm_kubernetes_cluster.primary.name
  resource_group_name = azurerm_kubernetes_cluster.primary.resource_group_name
}

# NOTE: The data block above is used to configured the kubernetes provider
# correctly, by adding a layer of indirectness. This is because of:
# https://registry.terraform.io/providers/hashicorp/kubernetes/latest/docs#stacking-with-managed-kubernetes-cluster-resources
provider "kubernetes" {
  host                   = data.azurerm_kubernetes_cluster.primary.kube_config[0].host
  client_certificate     = base64decode(data.azurerm_kubernetes_cluster.primary.kube_config[0].client_certificate)
  client_key             = base64decode(data.azurerm_kubernetes_cluster.primary.kube_config[0].client_key)
  cluster_ca_certificate = base64decode(data.azurerm_kubernetes_cluster.primary.kube_config[0].cluster_ca_certificate)
}

resource "kubernetes_namespace" "crs-ns" {
  metadata {
    name = "crs"
  }
}

resource "kubernetes_secret" "ghcr_auth" {
  metadata {
    name      = "ghcr-auth"
    namespace = kubernetes_namespace.crs-ns.metadata.0.name
  }
  type = "kubernetes.io/dockerconfigjson"
  data = {
    ".dockerconfigjson" = jsonencode({
      "auths" = {
        "https://ghcr.io" = {
          "auth" : base64encode("${var.github_username}:${var.github_pat}")
        }
      }
    })
  }
}

resource "kubernetes_deployment" "orchestrator" {
  metadata {
    name      = "orchestrator"
    namespace = kubernetes_namespace.crs-ns.metadata.0.name
  }
  spec {
    replicas = 2
    selector {
      match_labels = {
        app = "orchestrator"
      }
    }
    template {
      metadata {
        labels = {
          app = "orchestrator"
        }
      }
      spec {
        image_pull_secrets {
          name = kubernetes_secret.ghcr_auth.metadata[0].name
        }
        container {
          image = "ghcr.io/trailofbits/afc-crs-trail-of-bits/orchestrator:latest"
          name  = "orchestrator-container"
          port {
            container_port = 8000
          }
        }
      }
    }
  }
}

resource "kubernetes_service" "orchestrator" {
  metadata {
    name      = "orchestrator"
    namespace = kubernetes_namespace.crs-ns.metadata.0.name
  }
  spec {
    selector = {
      app = kubernetes_deployment.orchestrator.spec.0.template.0.metadata.0.labels.app
    }
    type = "NodePort"
    port {
      node_port   = 30201
      port        = 8000
      target_port = 8000
    }
  }
}
