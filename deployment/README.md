# Example AKS Cluster

## Overview

The following is an example on how to deploy an Azure Kubernetes Service cluster within an Azure subscription.

This configuration deploys an AKS cluster (`primary`) with two node pools:

- The default node pool (`sys`) - contains 2 system mode nodes
- A User node pool (`usr`) - contains 3 user mode nodes

The resource group name is generated with the `"random_pet"` resource from the `hashicorp/random` provider; and are prefixed with `example`

The VM Size for both pools are using `Standard_D5_v2` in this example. You can change this to suit your needs by editing the `vm_size` values in `main.tf`.

The standard `azure` networking profile is used.

## Prerequisites

- Azure CLI installed: [az cli install instructions](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli)
- Terraform installed: [terraform install instructions](https://developer.hashicorp.com/terraform/tutorials/azure-get-started/install-cli)
- Kubernetes CLI installed: [kubectl install instructions](https://kubernetes.io/docs/tasks/tools/#kubectl)
- `gettext` package
- An active Azure subscription.
- An account in Azure Entra ID.
- Access credentials to the competition Tailscale tailnet.
- Minikube installed, if you want to test the full CRS locally (linux/amd64 system recommended).

## Local Minikube Deployment

This section covers deploying the CRS locally using minikube on macOS or Linux.

### Local Prerequisites

- **Docker Desktop** (macOS/Windows) or Docker Engine (Linux)
- **minikube**: `brew install minikube` (macOS) or see [minikube install docs](https://minikube.sigs.k8s.io/docs/start/)
- **helm**: `brew install helm` (macOS)
- **kubectl**: `brew install kubectl` (macOS)

### Docker Desktop Resource Configuration

Docker Desktop has default resource limits that are typically too low for the full CRS deployment.

**To configure Docker Desktop resources (macOS):**
1. Open Docker Desktop > Settings > Resources
2. Allocate at least:
   - CPUs: 4-6 (depending on your machine)
   - Memory: 8-12 GB (10GB recommended for full deployment)
   - Disk: 80+ GB
3. Click "Apply & Restart"

**Important**: Minikube cannot use more resources than Docker Desktop allocates. If `env.template` specifies `MINIKUBE_CPU=6` and `MINIKUBE_MEMORY_GB=10`, but Docker Desktop only has 4 CPUs and 8GB RAM, minikube will fail to start or pods will remain Pending.

### Quick Start

```bash
cd deployment
cp env.template env

# Edit env to configure:
# - MINIKUBE_CPU/MINIKUBE_MEMORY_GB (match your Docker Desktop resources)
# - OPENAI_API_KEY and/or ANTHROPIC_API_KEY
# - Comment out GHCR_AUTH if building locally

make up
```

### Common Errors and Solutions

#### "Exiting due to RSRC_INSUFFICIENT_CORES" or memory errors

**Cause**: Minikube is requesting more resources than Docker Desktop has available.

**Solution**: Either increase Docker Desktop resources or reduce minikube resources in `env`:
```bash
export MINIKUBE_CPU=4
export MINIKUBE_MEMORY_GB=7
```

#### Pods stuck in Pending state

**Cause**: Kubernetes cannot schedule pods due to insufficient CPU or memory.

**Solution**: This is expected with limited resources. Check which pods are pending:
```bash
kubectl get pods -n crs | grep Pending
kubectl describe pod <pod-name> -n crs | grep -A5 Events
```

For local development, core services (redis, task-server, scheduler) should run. Fuzzer bots and multiple replicas may remain Pending.

#### Base64 decode errors with GHCR_AUTH

**Cause**: `GHCR_AUTH` is set to the placeholder value `<your-ghcr-base64-auth>`.

**Solution**: Either set a valid base64-encoded GitHub token or comment out the line:
```bash
# export GHCR_AUTH="<your-ghcr-base64-auth>"
```

For local builds, GHCR authentication is not required.

### Resource Expectations

With 8GB RAM allocated to Docker Desktop:

| Resource Setting | Expected Result |
|-----------------|-----------------|
| MINIKUBE_MEMORY_GB=10 | Minikube fails to start |
| MINIKUBE_MEMORY_GB=7 | Minikube starts, some pods Pending |
| MINIKUBE_MEMORY_GB=6 | More pods Pending, core services run |

### macOS ARM64 (Apple Silicon) Notes

- Minikube uses QEMU emulation for amd64 images on ARM64 Macs
- Some components may run slower due to emulation overhead
- The `gcr.io/oss-fuzz-base/base-runner` image is amd64-only
- For best performance, use a linux/amd64 machine or cloud VM

### Verifying the Deployment

```bash
# Check all pods
kubectl get pods -n crs

# Check core services are running
kubectl get pods -n crs | grep -E "(redis|task-server|scheduler)"

# View logs for a specific service
kubectl logs -n crs -l app=scheduler --tail=50

# Port forward to access the API locally
kubectl port-forward -n crs service/buttercup-competition-api 31323:1323
```

### Azure

#### Login to Azure

`az login --tenant <your-tenant>` - will open authentication in a browser

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

- You can create a SPA several ways, the following describes using Azure cli.

```bash
az ad sp create-for-rbac --name "ExampleSPA" --role Contributor --scopes /subscriptions/<YOUR-SUBSCRIPTION-ID>
```

> Replace "ExampleSPA" with the name of the SPA you wish to create.  
> Replace `<YOUR-SUBSCRIPTION-ID>` with your Azure subscription ID.  
> If using resource group locks, additional configuration may be necessary which is out of scope of this example; e.g. adding the role `Microsoft.Authorization/locks/` for write, read and delete to the SPA.

On successful SPA creation, you will receive output similar to the following:

```bash
{
  "appId": "34df5g78-dsda1-7754-b9a3-ee699876d876",
  "displayName": "ExampleSPA",
  "password": "jfhn6~lrQQSH124jfuy96ksv_ILa2q128fhn8s",
  "tenant": "n475hfjk-g7hj-77jk-juh7-1234567890ab"
}
```

Make note of these values, they will be needed in the AKS deployment as the following environment variables:

```bash
TF_ARM_TENANT_ID="<tenant-value>"
TF_ARM_CLIENT_ID="<appID-value>"
TF_ARM_CLIENT_SECRET="<password-value>"
TF_ARM_SUBSCRIPTION_ID="<YOUR-SUBSCRIPTION-ID>"
```

### Environment Variables

Copy `env.template` to `env` and modify appropriately, following the comments there.
Based on the environment variables specified, you can do different kind of deployments, such as production, staging, local with minikube, etc.

### CRS HTTP basic auth

_WIP (Current example is using the `jmalloc/echo-server` image as a PoC)_  
The crs-webapp image expects the following environment variables to be passed to it for HTTP basic authentication:

- `CRS_KEY_ID` - The CRS's username/ID
- `CRS_KEY_TOKEN` - The CRS's password
- `COMPETITION_API_KEY_ID` - The competition APIs username/ID
- `COMPETITION_API_KEY_TOKEN` - The competition APIs password

These values can be generated with the following python calls:

```bash
key_id:
python3 -c 'import uuid; print(str(uuid.uuid4()))'

key_token:
python3 -c 'import secrets, string; print("".join(secrets.choice(string.ascii_uppercase + string.ascii_lowercase + string.digits) for _ in range(32)))'
```

### GitHub personal access token

_WIP (Current example is using the `jmalloc/echo-server` image as a PoC)_  
You will need to have a GitHub personal access token (PAT) scoped to at least `read:packages`.

To create the PAT, go to your account, `Settings` > `Developer settings` > `Personal access tokens`, and generate a Token (classic) with the scopes needed for your use case.

For this example, the `read:packages` scope is required.

Once you have your PAT, you will need to base64 encode it for use within `secrets.tf`:

```bash
echo -n "ghcr_username:ghcr_token" | base64 --wrap=0
```

> replace `ghcr_username` and `ghcr_token` with your GitHub username and your PAT respectively.

Add your base64 encoded credentials to `GHCR_AUTH`

## Remote Terraform State Storage

By default, terraform stores its state locally. It is best practice to store terraform state in a remote location.  
This can help with collaboration, security, recovery and scalability. To do this within Azure, you need to create resources to do so.

### Azure CLI

The following is an example of how to create the resources needed for remote state configuration.  
These resources will be used in the `backend.tf` configuration file.

- Create remote state resource group.

```bash
az group create --name example-tfstate-rg --location eastus
```

- Create storage account for remote state.

```bash
az storage account create --resource-group example-tfstate-rg --name examplestorageaccountname --sku Standard_LRS --encryption-services blob
```

- Create storage container for remote state

```bash
az storage container create --name tfstate --account-name examplestorageaccountname --auth-mode login
```

### backend.tf

Replace the values for `resource_group_name`, `storage_account_name`, `container_name` with the ones you created above.

```bash
terraform {
  backend "azurerm" {
    resource_group_name  = "example-tfstate-rg"
    storage_account_name = "examplestorageaccountname"
    container_name       = "tfstate"
    key                  = "terraform.tfstate"
  }
}
```

## Makefile

The deployment of the AKS cluster and its resources are performed by the `Makefile`, which leverages `crs-architecture.sh`. This wrapper utilizes several mechanisms to properly configure both the teraform and kubernetes environments.

## Deploy

- Log into your Azure tenant with `az login --tenant<your-tenant>`
- Clone this repository if needed: `git clone git@github.com:tob-challenges/example-crs-architecture.git /<local_dir>`
- Make required changes to `backend.tf`
- Make any wanted changes to `main.tf`, `outputs.tf`, `providers.tf`, and `variables.tf`
- Update `./env` with accurate values for each variable
- Run `make up` from within the `example-crs-architecture` directory
  This will execute a deployment of your cluster via a combination of terraform and kubectl based on your unique values in `./env`

## Useful Cluster Commands

- `az aks get-credentials --name <your-cluster-name> --resource-group <your-resource-group>` - retrieves access credentials and updates kubeconfig for the current cluster
- `kubectl get namespaces` - lists all namespaces
- `kubectl get -n crs-webservice all` - lists all resources within the crs-webservice namespace
- `kubectl get -n tailscale all` - lists all resources within the tailscale namespace
- `kubectl get pods -A` - lists all pods in all namespaces
- `kubectl config get-contexts` - lists the current contexts in your kubeconfig
- `kubectl describe deployment -n crs-webservice crs-webapp` - print detailed information about the deployment, crs-webapp
- `kubectl logs <podName>` - retrieves the stdout and stderr streams from the containers within the specified pod
- `kubectl get svc -A` - lists status of all services
- `kubectl get -n crs-webservice ingress` - lists the tailscale ingress address of your API
- `kubectl port-forward -n crs service/buttercup-competition-api 31323:1323` - make competition-api service available locally at port 31323

## State

- `terraform state list` - lists all resources in the deployment.
- `terraform state show '<resource>'` - replace `<resource>` with the resource you want to view from the `list` command

## Destroy

To tear down your AKS cluster run the following:

- Run `make down` from within the `example-crs-architecture` directory

## Reset / Redeploy CRS

To reset or redeploy a running CRS cluster:

- Run `make down && make up` from within the `example-crs-architecture` directory

## Clean

Optionally, you can run `make clean` to remove any generated files create from the included templates at runtime. This action is executed during `make up`.

## Clean up Azure infrastructure

See [CLEAN.md](CLEAN.md).
