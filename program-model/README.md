# Program Model

Indexes a program's source code to be queried by `seed-gen` and `patcher`.

## Setup

Build the `cscope` docker image and push to `trailofbits`.

```shell
git clone git@github.com:trailofbits/aixcc-cscope.git
cd aixcc-cscope/
git checkout buttercup

docker build -t aixcc-cscope -f aixcc.Dockerfile .
docker tag aixcc-cscope ghcr.io/trailofbits/buttercup-cscope:main
docker push ghcr.io/trailofbits/buttercup-cscope:main
```

You should see the `buttercup-cscope` [package](https://github.com/orgs/trailofbits/packages)

## Development

Sync, reformat, lint, and test before committing changes to this directory.

```shell
just all
```
