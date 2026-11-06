# Overview

<!-- Compatibility anchors for existing incoming links. -->
<a id="design-notes-archive"></a>


Look up Python APIs, CLI commands and configuration here. Use the product guides for task-oriented instructions, and the generated pages for the current argument and setting inventory.

## Python API

- [API overview](API.md): core components and imports.
- [Functions](api/agent.md): decorator parameters, metadata and execution behavior.
- [Runtime](api/runtime.md): model requests and runtime contracts.
- [Providers](api/providers.md): runtime creation and provider interfaces.

## CLI and configuration

| Guide | Generated detail |
|---|---|
| [CLI usage](cli.md) | [Global flags](cli/README.md) and the command pages in the sidebar. |
| [Configuration](config.md) | [Config keys](config-keys.md), defaults and apply timing. |
| [Provider setup](../models/providers.md) | [Provider registry](provider-registry.md), protocols and environment variable names. |

Generated pages have complete English and Chinese descriptions. Command names, flags, configuration keys and protocol values retain their source spelling in both languages. Their inventory comes from code and is regenerated with the site.

## Diagnostics

[Diagnostics bundles](diagnostics.md) explains what the support ZIP contains and how sensitive fields are redacted.

## Engineering design

The [Design tab](design/README.md) organizes current designs by subsystem. Each topic has one maintained document; design revisions update that document, while Git retains its history. Planned behavior is identified in implementation-status sections. These engineering explanations complement the product guides.
