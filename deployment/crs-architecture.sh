#!/usr/bin/env bash
set -e

##set ANSI escaape codes
NC='\033[0m'
RED='\033[1;31m'
GRN='\033[1;32m'
BLU='\033[1;36m'

#executes a series of terraform, az cli, and kubernetes commands to deploy or destroy an example crs architecture
# Get the directory of the current script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

echo -e "${BLU}Applying environment variables from ./env${NC}"
# shellcheck disable=SC1094
source ./env
if [ "$AZURE_ENABLED" = "true" ]; then
	echo -e "${GRN}Current azure account status:${NC}"
	az account show --query "{SubscriptionID:id, Tenant:tenantId}" --output table || echo -e "${RED}Error: Failed to retrieve azure account status${NC}"
fi

#deploy the AKS cluster and kubernetes resources function
up() {

	echo -e "${BLU}Applying environment variables to yaml from templates${NC}"
	CLIENT_BASE64=$(echo -n "$TF_VAR_ARM_CLIENT_SECRET" | base64)
	CRS_KEY_BASE64=$(echo -n "$CRS_KEY_TOKEN" | base64)
	COMPETITION_API_KEY_BASE64=$(echo -n "$COMPETITION_API_KEY_TOKEN" | base64)
	export CLIENT_BASE64
	export CRS_KEY_BASE64
	export COMPETITION_API_KEY_BASE64
	export TS_DNS_IP

	# Normalize boolean variables
	if [ "$(echo "$TAILSCALE_ENABLED" | tr '[:upper:]' '[:lower:]')" = "true" ]; then
		TAILSCALE_ENABLED="true"
	else
		unset TAILSCALE_ENABLED
	fi

	if [ "$(echo "$AZURE_ENABLED" | tr '[:upper:]' '[:lower:]')" = "true" ]; then
		AZURE_ENABLED="true"
	else
		unset AZURE_ENABLED
	fi

	if [ "$TAILSCALE_ENABLED" = "true" ]; then
		envsubst <k8s/base/tailscale-operator/operator.template >k8s/base/tailscale-operator/operator.yaml
	fi

	if [ "$AZURE_ENABLED" = "true" ]; then
		#deploy AKS resources in Azure
		echo -e "${BLU}Deploying AKS cluster Resources${NC}"
		terraform init
		terraform apply -auto-approve

		#set resource group name and kubernetes cluster name variables from terraform outputs
		KUBERNETES_CLUSTER_NAME=$(terraform output -raw kubernetes_cluster_name)
		RESOURCE_GROUP_NAME=$(terraform output -raw resource_group_name)

		echo -e "${GRN}KUBERNETES_CLUSTER_NAME is $KUBERNETES_CLUSTER_NAME"
		echo "RESOURCE_GROUP_NAME is $RESOURCE_GROUP_NAME${NC}"
		echo -e "${BLU}Retrieving credentials to access AKS cluster${NC}"
		#retrieve credentials to access AKS cluster

		az aks get-credentials --resource-group "$RESOURCE_GROUP_NAME" --name "$KUBERNETES_CLUSTER_NAME"
	else
		echo -e "${BLU}Deploying minikube cluster${NC}"
		minikube status | grep -q "Running" || minikube start --cpus=8 --memory=32g --disk-size=80g --driver=docker --kubernetes-version=stable
		echo -e "${GRN}Minikube cluster status:${NC}"
		minikube status

		echo -e "${BLU}Building local docker images${NC}"
		eval $(minikube docker-env)
		docker build -f "$SCRIPT_DIR"/../orchestrator/Dockerfile -t localhost/orchestrator:latest "$SCRIPT_DIR"/..
		docker build -f "$SCRIPT_DIR"/../fuzzer/dockerfiles/runner_image.Dockerfile -t localhost/fuzzer:latest "$SCRIPT_DIR"/..
		docker build -f "$SCRIPT_DIR"/../seed-gen/Dockerfile -t localhost/seed-gen:latest "$SCRIPT_DIR"/..
		docker build -f "$SCRIPT_DIR"/../patcher/Dockerfile -t localhost/patcher:latest "$SCRIPT_DIR"/..
		docker build -f "$SCRIPT_DIR"/../program-model/Dockerfile -t localhost/program-model:latest "$SCRIPT_DIR"/..
	fi

	# Create namespace if it doesn't exist
	kubectl create namespace crs || true

	# Set secrets
	GHCR_PAT=$(echo -n "$GHCR_AUTH" | base64 -d | cut -d: -f2)
	GHCR_USERNAME=$(echo -n "$GHCR_AUTH" | base64 -d | cut -d: -f1)
	echo -e "${BLU}Creating ghcr secret${NC}"
	kubectl delete secret ghcr --namespace crs || true
	kubectl create secret generic ghcr \
		--namespace crs \
		--from-literal=pat="$GHCR_PAT" \
		--from-literal=username="$GHCR_USERNAME" \
		--from-literal=scantron_github_pat="$SCANTRON_GITHUB_PAT" || echo -e "${GRN}ghcr secret already exists${NC}"


	kubectl create secret docker-registry docker-auth \
		--namespace crs \
		--docker-server=docker.io \
		--docker-username="$DOCKER_USERNAME" \
		--docker-password="$DOCKER_PAT" || echo -e "${GRN}docker-registry secret already exists${NC}"

	#deploy kubernetes resources in AKS cluster
	if [ "$TAILSCALE_ENABLED" = "true" ]; then
		kubectl apply -k k8s/base/tailscale-operator/
		kubectl apply -k k8s/base/tailscale-dns/

		echo -e "${BLU}Waiting for the service nameserver to exist${NC}"
		timeout 5m bash -c "until kubectl get svc -n tailscale nameserver > /dev/null 2>&1; do sleep 1; done" || echo -e "${RED}Error: nameserver failed to exist within 5 minutes${NC}"
		echo -e "${BLU}Waiting for nameserver to have a valid ClusterIP${NC}"
		timeout 5m bash -c "until kubectl get svc -n tailscale nameserver -o jsonpath='{.spec.clusterIP}' | grep -v '<none>' > /dev/null 2>&1; do sleep 1; done" || echo -e "${RED}Error: nameserver failed to obtain a valid CLusterIP within 5 minutes${NC}"
		TS_DNS_IP=$(kubectl get svc -n tailscale nameserver -o jsonpath='{.spec.clusterIP}')
		envsubst <k8s/base/tailscale-coredns/coredns-custom.template >k8s/base/tailscale-coredns/coredns-custom.yaml

		kubectl apply -k k8s/base/tailscale-coredns/
	fi

	# Install buttercup CRS
	echo -e "${BLU}Installing buttercup CRS${NC}"
	umask 077 # Ensure new files are created with permissions only for current user
	VALUES_TEMPLATE=${BUTTERCUP_K8S_VALUES_TEMPLATE:-k8s/values-aks.template}
	envsubst <"$VALUES_TEMPLATE" >k8s/values-overrides.crs-architecture.yaml
	helm upgrade --install buttercup --namespace crs ./k8s -f ./k8s/values-overrides.crs-architecture.yaml --create-namespace
	umask 022 # Reset umask to default value

	if [ "$TAILSCALE_ENABLED" = "true" ]; then
		kubectl apply -k k8s/base/tailscale-connections/
		echo -e "${BLU}Waiting for ingress hostname DNS registration${NC}"
		timeout 5m bash -c "until kubectl get ingress -n crs buttercup-task-server -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' | grep -q '.'; do sleep 1; done" || echo -e "${BLU}Error: Ingress hostname failed to be to set within 5 minutes${NC}"
		INGRESS_HOSTNAME=$(kubectl get ingress -n crs buttercup-task-server -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
		echo -e "${GRN}Your ingress DNS hostname is $INGRESS_HOSTNAME${NC}"
	fi

	echo -e "${GRN}Buttercup CRS installation complete${NC}"
}

#destroy the AKS cluster and kubernetes resources function
down() {
	down-k8s
	if [ "$AZURE_ENABLED" = "true" ]; then
		echo -e "${BLU}Destroying AKS cluster${NC}"
		terraform apply -destroy -auto-approve
	else
		minikube stop
	fi
}

# destroys the kubernetes resources only
down-k8s() {
	echo -e "${BLU}Deleting Kubernetes resource${NC}"
	set +e
	kubectl delete -k k8s/base/tailscale-connections/
	helm uninstall --wait --namespace crs buttercup
	kubectl delete -k k8s/base/tailscale-coredns/
	kubectl delete -k k8s/base/tailscale-dns/
	kubectl delete -k k8s/base/tailscale-operator/
	kubectl delete secret ghcr --namespace crs
	kubectl delete namespace crs
	set -e
}

case $1 in
up)
	up
	;;
down)
	down
	;;
down-k8s)
	down-k8s
	;;
*)
	echo -e "${RED}The only acceptable arguments are up and down${NC}"
	;;
esac
