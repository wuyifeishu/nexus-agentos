# Security Policy

## Supported Versions

| Version | Status             |
|---------|--------------------|
| 1.20.x  | Actively supported |
| 1.19.x  | Security fixes     |
| 1.18.x  | Security fixes     |
| < 1.18  | End of life        |

## Reporting a Vulnerability

**DO NOT open a public issue.** Email `security@agentos.dev` with description, steps to reproduce, impact, and any suggested fixes. Acknowledgment within 24h, fix timeline within 72h.

## Built-in Security Modules

| Module | Purpose |
|--------|---------|
| `agentos.security.guardrails` | PII/jailbreak/malicious-code detection |
| `agentos.security.audit_logger` | Immutable audit log with cryptographic chaining |
| `agentos.api.rate_limiter` | Per-tenant API rate limiting |
| `agentos.api.versioning` | API versioning with sunset enforcement |
| `agentos.config_validator` | Startup configuration validation |
| `agentos.core.cost_tracker` | LLM cost tracking with budget enforcement |
| `agentos.core.feature_flags` | Kill switches and percentage rollouts |

## Disclosure Timeline

- Critical: 72h + CVE
- High: 7 days
- Medium: next release cycle
- Low: next major release
