---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: 3e9b297b16411e0e0848fc0302358070_98ce249e74a111f1897e5254002afed2
    ReservedCode1: opfGcMbh3JZ2eyLNk/ZlYsYMG1MKlflRLR7ha+JM6fjLbqj3UGzzwl0fzz43RpFUXttOtU6IjxqJLMoDXntEe9y6StawjWORIWBPkP52x1JHMpCmtjh9GjQVwemSBUFqUmeDZE58iPhQgV2ZeovUk/NsGJ8lky8jq6UZzjbpzX0ieUe6vozKtk8960w=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: 3e9b297b16411e0e0848fc0302358070_98ce249e74a111f1897e5254002afed2
    ReservedCode2: opfGcMbh3JZ2eyLNk/ZlYsYMG1MKlflRLR7ha+JM6fjLbqj3UGzzwl0fzz43RpFUXttOtU6IjxqJLMoDXntEe9y6StawjWORIWBPkP52x1JHMpCmtjh9GjQVwemSBUFqUmeDZE58iPhQgV2ZeovUk/NsGJ8lky8jq6UZzjbpzX0ieUe6vozKtk8960w=
---

# Contributing to NexusAgentOS

Thanks for your interest in contributing.

## Getting Started

1. Fork the repo, clone locally.
2. Create a virtual env: `python -m venv .venv && source .venv/bin/activate`
3. Install deps: `pip install -e ".[dev]"`
4. Run tests: `pytest`

## Development Workflow

```
main ← your-feature-branch
```

- Branch off `main` for all changes.
- Keep PRs focused — one feature/fix per PR.
- Write tests for new functionality.
- Run `pytest` and `ruff check .` before pushing.

## Commit Convention

```
type(scope): description

feat(evolution): add behavior signal collector
fix(channels): handle wechat retry

types: feat | fix | docs | refactor | test | chore | perf
```

## Pull Requests

1. Push your branch and open a PR against `main`.
2. Fill the PR template completely.
3. CI must pass (tests + lint) before review.
4. At least one maintainer review required.

## Code Style

- Black for formatting (line length 100).
- Ruff for linting.
- Type hints required on all public APIs.
- Google-style docstrings.

## Issues

- Bug reports: use the bug report template.
- Feature requests: use the feature request template.
- Security issues: see SECURITY.md, do NOT open a public issue.

## License

By contributing, you agree your contributions will be licensed under the Apache 2.0 License.
*（内容由AI生成，仅供参考）*
