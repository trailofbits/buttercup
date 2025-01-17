# Demo fuzzer.

General idea here is we have a set of builders and a fuzzer bot managed through redis queues. 

All commands are suggestions based on vibes at the moment and not really tested...

## Building:
... have a linux box 
Install poetry  
```
curl -sSL https://install.python-poetry.org | python3 -
```

```
pyenv install 3.8
pyenv global 3.8
poetry shell
poetry install
```

## Demo prereqs

Nginx depedencies (this is to run the fuzz bot locally instead of in docker):
```
sudo apt-get install pcre2
```

```
git clone https://github.com/google/oss-fuzz.git
export OSS_FUZZ_PATH=$(pwd)/oss-fuzz
```

## Running:

### Start redis:

```
docker pull redis
docker run redis
export REDIS_IP=$(docker inspect \
  -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' <container>)
export REDIS_URL="redis://$REDIS_IP"
```

### Starting the orchestrator:

This orchestrator mocks the interactions of an actual orchestrator by receiving build outputs and adding them to a fuzzer distribution.

```
python fuzzing_infra/orchestrator.py --redis_url $REDIS_URL
```

## Starting a build bot

This starts a build bot that will build fuzzr harnesses using helper.py. Allow caching means it will be built directly in the ossfuzz directory. This mode allows for only building a harness once rather than snapshotting per request trees.
```
python fuzzing_infra/builder_bot.py  --redis_url $REDIS_URL --allow-caching
```

## Starting the fuzzer bot
```
python fuzzing_infra/fuzzer_bot.py --redis_url $REDIS_URL --timeout 120
```

## Sending a build request:

Creating a manual build request:
```
python fuzzing_infra/stimulate_build_bot.py --redis_url $REDIS_URL --target_package nginx --ossfuzz $OSS_FUZZ_PATH --engine libfuzzer --sanitizer address
```

This command should result in the builder emitting build logs and then fuzzer logs. 