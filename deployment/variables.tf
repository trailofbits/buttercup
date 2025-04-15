variable "resource_group_location" {
  type        = string
  default     = "eastus"
  description = "Location of the resource group."
}

variable "resource_group_name_prefix" {
  type        = string
  default     = "example"
  description = "Prefix of the resource group name that's combined with a random ID so name is unique in your Azure subscription."
}

variable "sys_node_count" {
  type        = number
  description = "The initial quantity of nodes for the node pool."
  default     = 2
}

variable "usr_node_count" {
  type        = number
  description = "The initial quantity of nodes for the node pool."
  default     = 3
}

variable "username" {
  type        = string
  description = "The admin username for the new cluster."
  default     = "azureadmin"
}

variable "vm_size" {
  type        = string
  description = "The size of the VM to use for the nodes."
  default     = "Standard_L16s"
}

variable "ARM_SUBSCRIPTION_ID" {
  type        = string
  description = "Azure subscription ID"
}

variable "ARM_TENANT_ID" {
  type        = string
  description = "Azure tenant ID"
}

variable "ARM_CLIENT_ID" {
  type        = string
  description = "Azure client ID"
}

variable "ARM_CLIENT_SECRET" {
  type        = string
  sensitive   = true
  description = "Azure client secret"
}
