# How to setup integration tests on AKS

```shell
cd deployment
# Create ci.tfvars
# Set ARM_CLIENT_ID, ARM_CLIENT_SECRET, ARM_TENANT_ID, ARM_SUBSCRIPTION_ID
# Set usr_node_count, resource_group_name_prefix

# Change backend.tf to use `ci-terraform.tfstate` as key

terraform init
terraform plan -var-file ci.tfvars  -out ci.plan
terraform apply ci.plan

terraform output -raw kube_config
# Copy the kube config in GitHub secret KUBECONFIG
```

Shutdown the cluster once CI is not needed anymore
```shell
terraform destroy
```
