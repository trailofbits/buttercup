# API

- Competitors will consume the API described by `competition-swagger-v0.1.yaml`
- Competitors will provide the API described by `crs-swagger-v0.1.yaml`

NOTE: The JSON and YAML documents contain the same information and are generated from the same source.

These files describe the CRS API and the Example Competition API. [Swagger](https://swagger.io/blog/api-strategy/difference-between-swagger-and-openapi/) is an ecosystem built around the [OpenAPI](https://www.openapis.org/what-is-openapi)
specification with which it is possible to render a UI documenting the API, to generate client code to interact with the API, and to generate
server code to be the API. In essence, the OpenAPI specification is a standard way of documenting HTTP APIs. This allows tools built to consume the description
to be portable across APIs.

The different components can be used as needed for different applications. The Example Competition API specification
is generated using inline code comments and served under the `/swagger/` path. A web framework specific third-party dependency that included the
swagger-ui was used to provide the endpoints.

## Viewing the UI

The provided Example Competition API will serve the swagger UI at `/swagger/index.html`. The spec is served at `/swagger/doc.json`
Competitors may find it useful to do something similar for their CRS.

Most webserver frameworks will have a package that can be used to help serve the UI. If this is not possible or you do not wish to use a third-party package,
the source can be downloaded from [https://github.com/swagger-api/swagger-ui/releases](https://github.com/swagger-api/swagger-ui/releases).
After unpacking the archive using tar or ZIP, the precompiled source can be found in the `dist` directory.

If you do not wish to integrate the UI directly into the CRS system it is still possible to use for development.

- Using the same method described above, download and unpack the release.
- Place any number of swagger specs inside the `swagger-ui/dist` folder.
- Start a basic webserver from the `swagger-ui/dist` folder. For example the built-in Python 3 webserver:

```bash
# PWD: swagger-ui/dist
python -m http.server
```

- Change the path to the swagger file at the top of your page to the desired file. For example, `/competition-swagger-v0.1.json` if you placed
  a swagger spec called `competition-swagger-v0.1.json` at `swagger-ui/dist/competition-swagger-v0.1.json`.
- This will only allow viewing the documentation. Experimenting with the API endpoints requires a running API server serving the spec file.
  If the spec is served from the API server and it supports CORS, it is possible to specify the full URL to the spec in the box.
  This will allow you to experiment with the API using the `Try it Out` button.

## Generating a Client or Server

It is possible to generate client or server code from the swagger documents. The documents are a best effort to provide a strongly typed schema but are not perfect.
Use the generators at your own discretion as they are not maintained by AIxCC and may not produce working code.

### OpenAPI Generator

OpenAPI generator is a fork and actively maintained continuation of the swagger-codegen project. The source code can be found here: [https://github.com/openapitools/openapi-generator](https://github.com/openapitools/openapi-generator).

To run the generator using docker or podman:

```bash
docker run --rm -v $PWD:/local openapitools/openapi-generator-cli generate \
          -i /local/competition-swagger-v0.1.json \
          -g  lang \
          -o /local/out
```

- `-v $PWD:/local` mounts the current working directory into the `/local` directory in the container.
  A different host path could be provided for `$PWD`. All paths used in the following steps would be relative to the new path instead of `$PWD`.
- All arguments after `openapitools/openapi-generator-cli` are passed to the generator CLI inside the container
- `-i /local/competition-swagger-v0.1.json` is the path relative to the current working directory of the swagger file. On the host, `competition-swagger-v-0.1.json` is located in `$PWD`.
  If you want to change the file or path it must be a descendant of `$PWD`.
- `-g  lang` is used to specify the generator to run. If you pass an invalid value it will list all of the options.
- `-o /local/out` is the path relative to the current working directory to output the generated code.
- A language specific config file can be optionally provided using `-c /local/path_to_config` [Project Docs](https://github.com/OpenAPITools/openapi-generator/blob/b218e238f4f6cac8c919a78b296d3062bdfec0be/docs/customization.md#customizing-the-generator).
  The available config options can be found using the `config-help -g lang` subcommand instead of `generate`.

To see all available options for the generate command:

```bash
docker run --rm -v $PWD:/local openapitools/openapi-generator-cli help generate
```
