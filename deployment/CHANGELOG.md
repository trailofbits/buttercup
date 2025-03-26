# CHANGELOG.md

## 2025-03-07

- Adds tailscale configuration for ingress
- Removes nginx-ingress component
- Removes cert-manager / letsencrypt component
- Removes cluster issuer component
- Updates to env variables
- Updates to README.md

## 2025-03-01

- Modified variable names
- Uppdated example deployment to use echo server from GHCR authenticated registry
- Implmented `Makefile` to drive deployment and teardown of architecture
- DNS records created during deploy (up) are removed during destroy (down)
- Updates to README.md

## 2025-02-20

- Moved kuberenetes resources out of terraform HCL due to inconsistencies and reliability concerns
- Terraform now only creates the initial AKS infrastructure
- Introduced kustomize manifests to deploy kubernetes resources into the AKS cluster
- Iintroduced wrapper script, crs-architecture, to manage the proper deployment of all environments and variables within
- Leveraging generic template files for kustomize usage of environment variables to simplify end user burden

## 2025-01-19

- Updates to outputs.tf
- Updates to variables.tf
- Changes hardcoded credentials environment variables
- Updates to README.md

## 2025-01-15

- Adds example CRS webservice docker image via deployment.tf
- Adds private load balancer for CRS webservice via deployment.tf
- Adds docker registry auth via secrets.tf
- Updates to providers.tf to supprt `kubernetes` provider
- Updates to README.md

## 2024-12-03

- Initial commit of example-crs-architecture
- Added linter rules to root of `example-crs-architecture` repository
