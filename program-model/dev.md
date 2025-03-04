# Dev

Documentation for developing Program Model.

## Kythe

Takes about 3 hours to build.

### Install Bazel

Follow [instructions](https://bazel.build/install/ubuntu#install-on-ubuntu). You will need to install a specific version of Bazel depending on what the `build` output below outputs.

### Install Dependencies

```shell
sudo apt install flex bison asciidoc graphviz source-highlight clang
```

### Download and build Kythe

From [documentation](https://kythe.io/getting-started/#build-a-release-of-kythe-using-bazel-and-unpack-it-in-optkythe)

```shell
git clone git@github.com:trailofbits/aixcc-kythe.git

cd aixcc-kythe/

bazel build //kythe/release

mkdir ../opt/

tar -zxf bazel-bin/kythe/release/kythe.tar.gz --directory ../opt/
```
