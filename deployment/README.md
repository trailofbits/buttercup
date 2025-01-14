# Deployment of the Trail of Bits AIxCC Finals CRS

## Pre-requisites

- Azure CLI installed: [az cli install instructions](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli)
- Terraform installed: [terraform install instructions](https://developer.hashicorp.com/terraform/tutorials/azure-get-started/install-cli)
- Kubernetes CLI installed: [kubectl install instructions](https://kubernetes.io/docs/tasks/tools/#kubectl)
- An active Azure subscription.
- An account in Azure Entra ID.

### Azure

#### Login to Azure

`az login --tenant aixcc.tech` - will open authentication in a browser

Show current tenant and subscription name:

`az account show --query "{SubscriptionID:id, Tenant:tenantId}" --output table`

Example output:

```bash
SubscriptionID                        Tenant
------------------------------------  ------------------------------------
<YOUR-SUBSCRIPTION-ID>                c67d49bd-f3ec-4c7f-b9ec-653480365699
```

### Service Principal Account

A service principal account (SPA) is required to automate the creation of resources and objects within your subscription.

You can create a SPA several ways, the following describes using azure cli.

```bash
az ad sp create-for-rbac --name "ExampleSPA" --role Contributor --scopes /subscriptions/<YOUR-SUBSCRIPTION-ID>
```

> Replace "ExampleSPA" with the name of the SPA you wish to create. Replace `<YOUR-SUBSCRIPTION-ID>` with your azure subscription ID.
> If using resource group locks, additional configuration may be neccessary which is out of scope of this example; e.g. adding the role `Microsoft.Authorization/locks/` for write, read and delete to the SPA.

On successful SPA creation, you will receive output similar to the following:

```bash
{
  "appId": "34df5g78-dsda1-7754-b9a3-ee699876d876",
  "displayName": "ExampleSPA",
  "password": "jfhn6~lrQQSH124jfuy96ksv_ILa2q128fhn8s",
  "tenant": "n475hfjk-g7hj-77jk-juh7-1234567890ab"
}
```

Make note of these values, they will be used in the AKS deployment as the following environment variables:

```bash
ARM_TENANT_ID="<tenant-value>"
ARM_CLIENT_ID="<appID-value>"
ARM_CLIENT_SECRET="<password-value>"
ARM_SUBSCRIPTION_ID="<YOUR-SUBSCRIPTION-ID>"
```

You can export these as environment variables from the host you're deploying from.

```bash
export ARM_CLIENT_ID="00000000-0000-0000-0000-000000000000"
export ARM_CLIENT_SECRET="12345678-0000-0000-0000-000000000000"
export ARM_TENANT_ID="10000000-0000-0000-0000-000000000000"
export ARM_SUBSCRIPTION_ID="20000000-0000-0000-0000-000000000000"
```

## Remote Terraform State Storage

By default the terraform state for the CRS is saved on Azure in the following resource:
```
    resource_group_name  = "tfstate-rg"
    storage_account_name = "tfstateserviceact"
    container_name       = "tfstate"
    key                  = "terraform.tfstate"
```

If you want to change the resources used to save the Terraform state, you may need to create other resources.

### Azure CLI

The following is an example of how to create the resources needed for remote state configuration.
These resources will be used in the `backend.tf` configuration file.

- Create remote state resource group.

```bash
az group create --name example-tfstate-rg --location eastus
```

- Create storage account for remote state.

```bash
az storage account create --resource-group example-tfstate-rg --name exampleserviceaccountname --sku Standard_LRS --encryption-services blob
```

- Create storage container for remote state

```bash
az storage container create --name tfstate --account-name exampleserviceaccountname --auth-mode login
```

### backend.tf

Replace the values for `resource_group_name`, `storage_account_name`, `container_name` with the ones you created above.

```bash
terraform {
  backend "azurerm" {
    resource_group_name  = "example-tfstate-rg"
    storage_account_name = "exampleserviceaccountname"
    container_name       = "tfstate"
    key                  = "terraform.tfstate"
  }
}
```

## Deploy

- Log into your Azure tenant with `az login --tenant aixcc.tech`
- Export the environment variables for your [SPA Configuration](#service-principal-account) if needed.
- Initialize terraform: `terraform init`
- Run plan: `terraform plan` - review output
- Deploy: `terraform apply`
  - type `yes` when prompted to apply

A handful of outputs will be provided based on `outputs.tf` when the apply completes.

You can see the outputs values with `terraform output` or `terraform output <output-name>`.

## State

- `terraform state list` - lists all resources in the deployment.
- `terraform state show '<resource>'` - replace `<resource>` with the resource you want to view from the `list` command

## Destroy

To teardown your AKS cluster run the following:

- `terraform destroy`
- Review the output on what is to be destroyed
- Type `yes` at the prompt

## Kubernetes interactions

Save the kube config file and make it available through `KUBECONFIG` env var:
```shell
terraform output --raw  kube_config >! kube.config
export KUBECONFIG=$(pwd)/kube.config
```

```shell
kubectl get namespaces
```

## Access kubernetes cluster nodes / services
```shell
kubectl port-forward service/orchestrator -n crs 18000:8000
```

Then access `127.0.0.1:18000`.


## Troubleshooting

### Error acquiring the state lock
```
Error: Error acquiring the state lock
│
│ Error message: state blob is already locked
│ Lock Info:
│   ID:        7a304f3a-6b83-34a1-6773-b70ec456e6cc
│   Path:      tfstate/terraform.tfstate
│   Operation: OperationTypeApply
│   Who:       ret2libc@macbookpro.lan
│   Version:   1.10.4
│   Created:   2025-01-14 12:56:49.352199 +0000 UTC
│   Info:
│
│
│ Terraform acquires a state lock to protect the state from being written
│ by multiple users at the same time. Please resolve the issue above and try
│ again. For most commands, you can disable locking with the "-lock=false"
│ flag, but this is not recommended.
╵
```

First, ensure that someone else is not really running some `terraform` command
concurrently. If that's not the case, the state file might have not been
unlocked (e.g. you CTRL-C terraform at some point and it did not unlocked the
file before exiting), you can try adding the `-lock=false` as specified, or, if
that does not work, go to the [Azure portal](https://portal.azure.com), open the
`tfstate-rg` Resource Group, `tfstateserviceact`, then in Data Storage >
Containers select `tfstate`. Select the `terraform.tfstate` blob and click
`Break lease.
