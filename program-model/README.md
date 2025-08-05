# Program Model

Indexes a program's source code to be queried by `seed-gen` and `patcher`.

## Dependencies

* [CodeQuery](https://ruben2020.github.io/codequery/)
* <https://github.com/trail-of-forks/buttercup-cscope>
* [Tree-sitter](https://tree-sitter.github.io/tree-sitter/)

## Quick Test

```shell
./test-docker.sh quick
```

## Development

Before committing changes to this directory: reformat, lint, and ensure all tests pass.

```shell
make sync reformat lint

./test-docker.sh full
```
