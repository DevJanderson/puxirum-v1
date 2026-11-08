# Puxirum

A deterministic software factory: GitHub issues in, merged pull requests out.

*Puxirum* is an Amazonian word of Tupi origin for collective work, where a community gathers so each person does a
part of the job until it is done.

Status: early development. See [docs/design.md](docs/design.md).

## Development

```bash
python3 -m unittest discover -s tests -t .
ruff check src tests
ruff format --check src tests
mypy
```

## License

Copyright (C) 2026 Janderson Lira.

[GPLv3](LICENSE) (GPL-3.0-only). You can use, modify and share this code, and any version you distribute must also
be released under GPLv3.
