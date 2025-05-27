# Clean Azure

Sometimes the cloud infrastructure fills up on disk space and needs to be cleaned.

## Login into Azure

```shell
az login --tenant=aixcc.tech
```

## Configure kubectl to use the Azure CI cluster

```shell
az aks get-credentials --name cluster-allowing-foal  --resource-group gh-ci-smashing-mosquito
```

## Get list of nodes

```shell
kubectl get nodes
# Note the nodes named "-vmss00000{9,a,b,c}" on DevBudget
```

## Run a debug pod on a listed node

For example, assume we've identified node `aks-usr-26512064-vmss00000c` from the above list.

```shell
kubectl debug node/aks-usr-26512064-vmss00000c -it --image=mcr.microsoft.com/aks/fundamental/base-ubuntu:v0.0.11
```

## Clean images

```shell
chroot /host
crictl rmi --prune
```
