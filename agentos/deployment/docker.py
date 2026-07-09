"""AgentOS deployment — Docker and orchestration helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# ── Dockerfile generator ──────────────────────────────────────────────────────


@dataclass
class DockerConfig:
    """Docker 部署配置。"""

    python_version: str = "3.11"
    base_image: str = "python:{python_version}-slim"
    workdir: str = "/app"
    port: int = 8000
    entry_module: str = "agentos.cli.serve"
    extra_packages: list[str] = field(default_factory=list)
    env_vars: dict[str, str] = field(default_factory=dict)
    user: str = "appuser"


def generate_dockerfile(config: DockerConfig | None = None) -> str:
    """Generate a production-ready Dockerfile for an AgentOS project."""
    cfg = config or DockerConfig()
    base = cfg.base_image.format(python_version=cfg.python_version)

    lines = [
        f"FROM {base}",
        "",
        'LABEL org.opencontainers.image.source="https://github.com/agentos/agentos"',
        "",
        "# System dependencies",
        "RUN apt-get update && apt-get install -y --no-install-recommends \\",
        "    curl ca-certificates \\",
        "    && rm -rf /var/lib/apt/lists/*",
        "",
        "# Create non-root user",
        f"RUN groupadd -r {cfg.user} && useradd -r -g {cfg.user} {cfg.user}",
        "",
        f"WORKDIR {cfg.workdir}",
        "",
        "# Install Python dependencies",
        "COPY requirements.txt .",
        "RUN pip install --no-cache-dir -r requirements.txt",
        "",
        "# Copy application",
        "COPY . .",
        "RUN pip install --no-cache-dir -e .",
        "",
    ]

    if cfg.extra_packages:
        lines.append(f"RUN pip install --no-cache-dir {' '.join(cfg.extra_packages)}")
        lines.append("")

    for k, v in cfg.env_vars.items():
        lines.append(f"ENV {k}={v}")
    if cfg.env_vars:
        lines.append("")

    lines += [
        "# Security: drop root",
        f"USER {cfg.user}",
        "",
        "# Health check",
        "HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \\",
        f"    CMD curl -f http://localhost:{cfg.port}/health || exit 1",
        "",
        f"EXPOSE {cfg.port}",
        "",
        f'ENTRYPOINT ["python", "-m", "{cfg.entry_module}"]',
    ]

    return "\n".join(lines)


# ── docker-compose generator ──────────────────────────────────────────────────


@dataclass
class ComposeService:
    """Compose 服务定义。"""

    name: str
    build_context: str = "."
    port: int = 8000
    env_file: str = ".env"
    volumes: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    command: str = ""


@dataclass
class ComposeConfig:
    """Compose 编排配置。"""

    services: list[ComposeService] = field(default_factory=list)
    project_name: str = "agentos"
    network_name: str = "agentos-net"


def generate_docker_compose(config: ComposeConfig) -> str:
    """Generate a docker-compose.yml for an AgentOS project."""
    lines = ['version: "3.9"', "", "services:"]

    for svc in config.services:
        lines.append(f"  {svc.name}:")
        lines.append("    build:")
        lines.append(f"      context: {svc.build_context}")
        lines.append("    ports:")
        lines.append(f'      - "{svc.port}:{svc.port}"')
        if svc.env_file:
            lines.append("    env_file:")
            lines.append(f"      - {svc.env_file}")
        if svc.volumes:
            lines.append("    volumes:")
            for v in svc.volumes:
                lines.append(f"      - {v}")
        if svc.depends_on:
            lines.append("    depends_on:")
            for d in svc.depends_on:
                lines.append(f"      - {d}")
        if svc.command:
            lines.append(f"    command: {svc.command}")
        lines.append("")

    lines += [
        "networks:",
        "  default:",
        f"    name: {config.network_name}",
    ]

    return "\n".join(lines)


# ── Deployment helper ─────────────────────────────────────────────────────────


def write_deployment_files(
    output_dir: str | Path,
    docker_config: DockerConfig | None = None,
    compose_config: ComposeConfig | None = None,
) -> list[Path]:
    """Write Dockerfile and docker-compose.yml to output_dir.  Returns written paths."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    df_path = out / "Dockerfile"
    df_path.write_text(generate_dockerfile(docker_config))
    written.append(df_path)

    compose = compose_config or ComposeConfig(services=[ComposeService(name="agentos")])
    dc_path = out / "docker-compose.yml"
    dc_path.write_text(generate_docker_compose(compose))
    written.append(dc_path)

    return written
