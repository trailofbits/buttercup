# Project Source Language Determination

As part of evaluating a patch, Scantron has to determine if it only modifies files in the target project's language.

Scantron uses [go-enry](https://github.com/go-enry/go-enry) v2.9.2 to determine a file's language. This folder contains binaries so that you can run the same process outside of Scantron.

## Binaries

These can be found in the [dist](dist) folder.

## Usage

`identifier` accepts a language, either `java` or `c`, and a path to a source file. It returns both a string boolean and a return code indicating whether the source file is in the specified language.

```bash
$ ./identifier --help
Identifies file type

Usage:
  identifier [flags]

Flags:
  -h, --help                help for identifier
      --language Language   "java" or "c"
      --path string         Path to file to check

$ ./identifier --language java --path ~/Source.java
true
$ echo $?
0

$ ./identifier --language c --path ~/Source.java
false
$ echo $?
1

$ ./identifier --language c --path ~/nonexistent
Error: open /home/user/nonexistent
$ echo $?
201
```
