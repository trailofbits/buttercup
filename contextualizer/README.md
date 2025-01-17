# Contextualizer

Details about implementation and design decisions can be found [here](https://docs.google.com/document/d/1M_edNTDh8o6n_jDLGYgEeSKfoDLWEkCw8iyd-w9esRo).

## Setup

- Install and create python environment with [Pyenv](https://github.com/pyenv/pyenv)

  ```bash
  pyenv install 3.12
  pyenv local 3.12
  ```

- Build contextualizer

  ```bash
  make dev
  source env/bin/activate
  ```

- Run contextualizer

  ```bash
  contextualizer --help
  ```
