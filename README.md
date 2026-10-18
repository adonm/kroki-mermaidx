# kroki-mermaidx

A browserless **Mermaid** companion service for [Kroki](https://kroki.io),
powered by [mermaidx](https://pypi.org/project/mermaidx/) — Mermaid running in
QuickJS instead of headless Chromium.

The service registers itself with a Kroki gateway as the `mermaidx` diagram type
using the gateway's [companion service discovery](https://docs.kroki.io/kroki/setup/configuration/#_companion_service_discovery)
API. It lives in a separate container: the existing Mermaid companion is
untouched, and users opt in by simply using the `mermaidx` diagram type.

```
POST https://kroki.example/mermaidx/svg   # instead of /mermaid/svg
POST https://kroki.example/mermaidx/png
POST https://kroki.example/mermaidx/pdf
```

This project is the standalone companion suggested in
[yuzutech/kroki#2143](https://github.com/yuzutech/kroki/pull/2143) and tracks
[yuzutech/kroki#2142](https://github.com/yuzutech/kroki/issues/2142).

## Why

- **No browser, no Node.js, no npm.** mermaidx renders Mermaid in QuickJS and
  rasterizes with resvg: a small image, a fraction of the memory, and no
  Chromium lifecycle to babysit.
- **A separate service.** The built-in Mermaid companion keeps using headless
  Chromium; this project can be evaluated, versioned and scaled independently.
- **Opt-in per request.** Use `mermaidx` as the diagram type at runtime. No
  server-side flag to flip, no second code path inside the Mermaid container.

## Quick start

### Docker Compose

[`compose.yaml`](compose.yaml) starts a Kroki gateway with companion service
discovery enabled and this companion registered as `mermaidx`:

```bash
docker compose up --build
curl -sS -X POST http://localhost:8000/mermaidx/svg \
  -H 'Content-Type: text/plain' \
  --data-binary 'flowchart LR; A-->B-->C' -o diagram.svg
```

> [!IMPORTANT]
> Companion service discovery is **disabled by default** and always disabled
> while Kroki runs in `SECURE` safe mode (the default, including on kroki.io).
> The Compose file explicitly sets `KROKI_SAFE_MODE=SAFE` and
> `KROKI_ENABLE_COMPANION_DISCOVERY=true`. Only enable it on a trusted network.

### Without Docker

```bash
uv sync
uv run kroki-mermaidx            # serves on 0.0.0.0:8006, discovery disabled
```

Render directly against the companion:

```bash
curl -sS -X POST http://localhost:8006/mermaidx/svg \
  -H 'Content-Type: text/plain' \
  --data-binary 'sequenceDiagram; Alice->>Bob: Hi' -o diagram.svg
```

To register with a Kroki gateway, point it at your gateway first:

```bash
KROKI_URL=http://localhost:8000 \
KROKI_COMPANION_HOST=localhost \
KROKI_COMPANION_PORT=8006 \
uv run kroki-mermaidx
```

The gateway must run with `KROKI_SAFE_MODE=SAFE` and
`KROKI_ENABLE_COMPANION_DISCOVERY=true`; use
`KROKI_COMPANION_REGISTRATION_TOKEN` on both sides to protect the `/services`
API.

### Published image

Multi-arch images (`linux/amd64`, `linux/arm64`) are published to the GitHub
Container Registry from every `v*` tag:

```bash
docker run --rm -p 8006:8006 ghcr.io/adonm/kroki-mermaidx:latest
```

In Compose, replace `build: .` with the published image:

```yaml
  mermaidx:
    image: ghcr.io/adonm/kroki-mermaidx:latest
```

## API

| Endpoint              | Description                                              |
| --------------------- | -------------------------------------------------------- |
| `POST /mermaidx/svg`  | Mermaid source in the body, `image/svg+xml` out           |
| `POST /mermaidx/png`  | Mermaid source in the body, `image/png` out               |
| `POST /mermaidx/pdf`  | Mermaid source in the body, `application/pdf` out         |
| `GET /health`         | Liveness: always `200` while the process is serving       |
| `GET /ready`          | Readiness: `503` until registered (when discovery is on)  |
| `GET /`               | Service information                                       |

Errors use the same JSON envelope as the built-in companions:

```json
{
  "error": {
    "name": "SyntaxError",
    "message": "Parse error on line 3: ...",
    "stacktrace": ""
  }
}
```

### Diagram options

Query parameters are forwarded to Mermaid as configuration, exactly like the
Mermaid companion: `?theme=dark`, `?flowchart_curve=linear`, ...

Keys use `_` for nested properties (`flowchart_curve` becomes
`flowchart.curve`) and `-` for camelCase (`gantt_bar-gap` becomes
`gantt.barGap`). Note that Kroki lowercases every query parameter before
forwarding it, so camelCase Mermaid keys (e.g. `themeVariables_primaryColor`)
only work when calling the companion directly, not through the gateway — the
same limitation applies to the built-in Mermaid companion.

Raster options are handled by mermaidx itself and apply to PNG and PDF output:

| Option                      | Description                                              |
| --------------------------- | -------------------------------------------------------- |
| `width`, `height`           | Output size in pixels (aspect ratio is preserved)        |
| `scale`                     | Size multiplier when `width`/`height` are not given      |
| `background`                | CSS background color (transparent by default)            |
| `pdf_format`, `pdf_landscape`, `pdf_margin` | PDF paper format, orientation and margin |

For security and resource-exhaustion reasons, `maxTextSize`, `maxEdges`,
`securityLevel`, `secure`, `startOnLoad` and `safeMode` cannot be overridden
per request.

## Configuration

| Environment variable                   | Default       | Description                                                                |
| -------------------------------------- | ------------- | -------------------------------------------------------------------------- |
| `MERMAIDX_NAME`                        | `mermaidx`    | Diagram type name (also the route prefix and the registered service name)  |
| `MERMAIDX_BIND_HOST`                   | `0.0.0.0`     | Bind address                                                               |
| `MERMAIDX_BIND_PORT`                   | `8006`        | Bind port                                                                  |
| `MERMAIDX_FORMATS`                     | `svg,png,pdf` | Advertised output formats                                                  |
| `MERMAIDX_BIN`                         | `mermaidx`    | mermaidx executable                                                        |
| `MERMAIDX_MAX_TEXT_SIZE`               | `50000`       | Maximum diagram source length in characters                                |
| `MERMAIDX_MAX_EDGES`                   | `500`         | Mermaid `maxEdges` limit                                                   |
| `MERMAIDX_MAX_BODY_SIZE`               | `1mb`         | Maximum request body size                                                  |
| `MERMAIDX_CONVERT_TIMEOUT`             | `10`          | Seconds before a render is killed and reported as `408`                    |
| `MERMAIDX_MAX_CONCURRENCY`             | `4`           | Maximum concurrent mermaidx processes (further requests queue)             |
| `MERMAIDX_LOG_LEVEL`                   | `info`        | Log level                                                                  |
| `KROKI_URL`                            | *(unset)*     | Kroki gateway base URL. Unset disables service discovery                   |
| `KROKI_COMPANION_HOST`                 | `mermaidx`    | Host advertised to the gateway (a DNS name, not a loopback/private IP)     |
| `KROKI_COMPANION_PORT`                 | bind port     | Port advertised to the gateway                                             |
| `KROKI_COMPANION_REGISTRATION_TOKEN`   | *(unset)*     | Bearer token for the gateway `/services` API                               |
| `MERMAIDX_HEARTBEAT_INTERVAL`          | `30`          | Seconds between heartbeats (must stay below the gateway TTL, `90` by default) |
| `MERMAIDX_REGISTER_RETRY_INITIAL`      | `1`           | Initial retry delay after a failed registration, in seconds                |
| `MERMAIDX_REGISTER_RETRY_MAX`          | `30`          | Maximum retry delay after a failed registration, in seconds                |

## How registration works

1. On startup (with `KROKI_URL` set) the service `POST`s its name, version,
   formats, host and port to the gateway's `/services` endpoint.
2. Every `MERMAIDX_HEARTBEAT_INTERVAL` seconds it sends a heartbeat. If the
   gateway restarted (heartbeat `404`), it registers again. If the name is
   already taken by our own previous registration (container restart before
   the gateway TTL expired), it adopts that registration when the version
   matches.
3. On graceful shutdown it unregisters, so a scaled-down deployment does not
   have to wait for the TTL.

Because the gateway keeps registrations in memory, run **one replica** of the
companion per diagram type; multiple replicas would race for the same name.
Scale vertically with `MERMAIDX_MAX_CONCURRENCY` (memory: roughly 70–100 MB per
concurrent mermaidx process).

## Differences from the Chromium Mermaid companion

mermaidx currently bundles **Mermaid 11.16.0**, while the Kroki Mermaid
companion bundles **Mermaid 12.1.0**. Beyond that, the known deltas are the ones
documented on [yuzutech/kroki#2142](https://github.com/yuzutech/kroki/issues/2142):
Gantt PNG width, remote image nodes, and traceback-shaped error bodies.

## Development

```bash
uv sync                 # install runtime + dev dependencies
uv run pytest           # tests (renderer tests need mermaidx, installed by uv)
uv run ruff check .     # lint
uv run ruff format --check .
uv run kroki-mermaidx
```

The renderer spawns the `mermaidx` CLI once per request, with a hard timeout
and crash isolation. Rendering is fully offline: no diagram source or URL is
sent over the network.

## License

MIT. Not an official Kroki project.
