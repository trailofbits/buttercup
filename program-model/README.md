# Program Model

Indexes a program into a graph database.

## Setup

## Usage

```shell
(type -p wget >/dev/null || (sudo apt update && sudo apt-get install wget -y)) \
	&& sudo mkdir -p -m 755 /etc/apt/keyrings \
        && out=$(mktemp) && wget -nv -O$out https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        && cat $out | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null \
	&& sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
	&& echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
	&& sudo apt update \
	&& sudo apt install gh -y
sudo apt update
sudo apt install gh

github.com -> settings -> developer settings -> personal access tokens -> tokens (classic) -> generate new token
select "repo" scope
select "read:org" scope

gh auth login
GitHub.com
SSH
No
Paste an authentication token

gh release download v0.0.2 -R github.com/trailofbits/aixcc-kythe
<authenticate URL in browser for the first time>
rm kythe-v0.0.67.tar.gz

sudo apt install just

cd afc-crs-trail-of-bits/
cp env.template .env

mkdir crs_scratch/
git clone --recursive git@github.com:aixcc-finals/example-libpng.git crs_scratch/libpng

just run-indexer

<todo>

docker compose down
```
