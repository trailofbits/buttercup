# Program Model

Indexes a program's source code to be queried by `seed-gen` and `patcher`.

## Development

Setup

```shell
cd buttercup/
make setup-local
make validate
make deploy-local
```

Logs & Debug Container

```shell
kubectl logs -n crs -l app=program-model --tail=-1 --prefix
kubectl get pods -n crs | grep program-model
kubectl exec -it -n crs <pod-name> -- /bin/bash
```

Submit Test Challenge

```shell
make test
```

```shell
kubectl port-forward -n crs service/buttercup-ui 31323:1323
./orchestrator/scripts/challenge.sh
```

Monitor Logs

```shell
kubectl logs -f -n crs -l app=program-model-api --tail=-1 --prefix
```

Bring down, make changes, and bring the CRS back up again

```shell
make clean

<debug>

make deploy
```

Test before committing changes

```shell
cd program-model/
just all
```

Clean up

```shell
make clean-local
```
