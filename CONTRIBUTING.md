# Contributing

Thank you for helping improve Firecloud Forecast. Use English for public issues,
pull requests, documentation, code comments, and user-facing messages.

## Development setup

Fork or clone the repository, install Python 3.11+ and uv, then run:

```bash
uv sync --frozen
uv run firecloud --help
uv run pytest
```

The default suite excludes tests marked `integration`. It exercises synthetic
weather fields, scalar/grid agreement, physical invariants, product metadata,
cache behavior, and command-line output.

Run real-data checks deliberately:

```bash
uv run pytest -m integration
```

Integration tests use external services and may download large files. A network
failure is not evidence of a scoring regression; report the failing source and
request separately. Standard pull-request CI runs the offline suite.

## Propose a change

For a bug, include a minimal reproduction, environment details, expected and
actual behavior, and relevant metadata. Remove credentials and private paths from
logs. For a new feature or algorithm change, open an issue first to agree on the
input, output, scope, and acceptance criteria.

Keep pull requests focused. Explain the problem, the resulting behavior, and how
you verified it. Preserve existing public interfaces unless the change includes
a migration plan. Documentation-only changes do not need new unit tests.

For physics changes, document the assumption and source, add a discriminating
synthetic case, and compare against the existing implementation. Never treat
passing regression tests as independent evidence of real-world forecast skill.
See [methodology](research/methodology.md) and [architecture](docs/architecture.md).

Before submitting:

```bash
uv lock --check
uv run pytest
uv build
git diff --check
```

Do not commit downloaded weather data, forecast output, caches, secrets, private
reference PDFs, personal execution logs, or generated HTML. Small deterministic
fixtures and paper figures are appropriate when their provenance is clear.

## Coordination and conduct

Be respectful, explain disagreements with evidence, and distinguish observations
from assumptions. The issue tracker holds durable requirements; personal execution
notes stay local. Agents sharing a checkout follow
[AGENTS.md](https://github.com/NickZhuxy/firecloud-forecast/blob/main/AGENTS.md).

Contributions are provided under the repository's [MIT License](LICENSE). Ensure
you have the right to contribute any code, data, or documentation you submit.
