"""  # noqa: E501
AgentOS Skill Marketplace — Registry。

核心能力:
  - 本地注册表：~/.agentos/marketplace/installed.json
  - PyPI 发现：搜索 agentos-skill-* 前缀包
  - 安装/卸载/更新/搜索
  - 多格式兼容：agentos / openclaw / MCP / generic

目录结构:
  ~/.agentos/marketplace/
    installed.json        # 已安装清单
    skills/
      <name>/             # 每个 skill 一个目录
        manifest.yaml
        ...
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from agentos.marketplace.manifest import SkillFormat, SkillManifest

MARKET_DIR = Path.home() / ".agentos" / "marketplace"
INSTALLED_JSON = MARKET_DIR / "installed.json"
SKILLS_DIR = MARKET_DIR / "skills"
PYPI_SKILL_PREFIX = "agentos-skill-"


class System:
    """简化后的 PyPI 搜索调用——用 pip 查询比 httpx 解析 JSON API 更可靠。"""


@dataclass
class SearchResult:
    """搜索结果。"""

    name: str
    version: str
    description: str
    source: str  # pypi | github | local
    installable: bool = True
    pypi_package: str = ""
    skill_count: int = 0


@dataclass
class InstallResult:
    """安装结果。"""

    success: bool
    manifest: SkillManifest | None = None
    error: str = ""
    pypi_package: str = ""
    install_type: str = ""  # pypi_install | local_copy | git_clone
    dep_installed: list[str] = field(default_factory=list)


class SkillRegistry:
    """技能市场注册表。

    支持三种安装源：
      1. PyPI 包（agentos-skill-* 前缀）
      2. 本地目录（含 manifest.yaml/json）
      3. GitHub 仓库（git clone + pip install）

    每个 skill 安装后：
      - manifest 存入 installed.json
      - 源文件复制到 ~/.agentos/marketplace/skills/<name>/
      - pip 依赖自动安装
    """

    def __init__(self):
        self._ensure_dirs()

    # ── 搜索 ──

    def search(self, query: str = "", max_results: int = 20) -> list[SearchResult]:
        """搜索技能市场。query 为空时返回热门。"""
        results: list[SearchResult] = []

        # 1. 搜索 PyPI（agentos-skill-*）
        try:
            r = subprocess.run(
                (
                    [sys.executable, "-m", "pip", "search", f"{PYPI_SKILL_PREFIX}{query}"]
                    if query
                    else [sys.executable, "-m", "pip", "search", PYPI_SKILL_PREFIX]
                ),
                capture_output=True,
                text=True,
                timeout=15,
                env={**os.environ, "PIP_DISABLE_PIP_VERSION_CHECK": "1"},
            )
            for line in r.stdout.split("\n"):
                line = line.strip()
                if line and PYPI_SKILL_PREFIX in line and not line.startswith("ERROR"):
                    parts = line.split()
                    pkg_name = parts[0]
                    version = parts[1].lstrip("(").rstrip(")") if len(parts) > 1 else "?"
                    desc = " ".join(parts[2:]) if len(parts) > 2 else ""
                    skill_name = pkg_name.replace(PYPI_SKILL_PREFIX, "").replace("-", "_")
                    # 去重
                    if not any(r.name == skill_name for r in results):
                        results.append(
                            SearchResult(
                                name=skill_name,
                                version=version,
                                description=desc,
                                source="pypi",
                                pypi_package=pkg_name,
                            )
                        )
        except Exception:
            pass

        # 2. 如果 pip search 不可用，尝试直接查 PyPI JSON API
        if not results and query:
            try:
                import urllib.request

                url = f"https://pypi.org/pypi/{PYPI_SKILL_PREFIX}{query}/json"
                req = urllib.request.Request(url, headers={"User-Agent": "AgentOS-Marketplace/1.0"})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = json.loads(resp.read())
                    info = data.get("info", {})
                    skill_name = query.replace("-", "_")
                    results.append(
                        SearchResult(
                            name=skill_name,
                            version=info.get("version", "?"),
                            description=info.get("summary", ""),
                            source="pypi",
                            pypi_package=f"{PYPI_SKILL_PREFIX}{query}",
                        )
                    )
            except Exception:
                pass

        # 3. 限制结果数
        return results[:max_results]

    def list_installed(self) -> list[SkillManifest]:
        """列出所有已安装 skill。"""
        data = self._load_installed()
        manifests = []
        for entry in data.get("skills", []):
            m = SkillManifest.from_dict(entry)
            if m.name:
                manifests.append(m)
        return sorted(manifests, key=lambda m: m.name)

    def get_installed(self, name: str) -> SkillManifest | None:
        """获取已安装 skill 的 manifest。"""
        for m in self.list_installed():
            if m.name == name:
                return m
        return None

    # ── 安装 ──

    def install(self, name_or_path: str) -> InstallResult:
        """安装一个 skill。

        自动判断安装源：
          1. 本地目录（包含 manifest.yaml/json 时复制安装）
          2. Git URL（含 github.com 时 git clone）
          3. PyPI 包（pip install agentos-skill-<name>）
        """
        target = name_or_path.strip()

        # ─ 源 1: 本地目录 ─
        local_path = Path(name_or_path)
        if local_path.is_dir():
            manifest_file = local_path / "skill.yaml"
            if not manifest_file.exists():
                manifest_file = local_path / "skill.json"
            if not manifest_file.exists():
                manifest_file = local_path / "manifest.yaml"
            if not manifest_file.exists():
                manifest_file = local_path / "manifest.json"
            if manifest_file.exists():
                return self._install_local(local_path, manifest_file)
            return InstallResult(
                success=False, error=f"No manifest (skill.yaml/json) found in {local_path}"
            )

        # ─ 源 2: GitHub URL ─
        if "github.com" in name_or_path:
            return self._install_github(name_or_path)

        # ─ 源 3: PyPI 包 ─
        return self._install_pypi(target)

    def uninstall(self, name: str) -> bool:
        """卸载一个 skill。"""
        existing = self.get_installed(name)
        if not existing:
            return False

        # 删除 skill 目录
        skill_dir = SKILLS_DIR / name
        if skill_dir.exists():
            shutil.rmtree(skill_dir)

        # 更新 installed.json
        data = self._load_installed()
        data["skills"] = [s for s in data.get("skills", []) if s.get("name") != name]
        self._save_installed(data)
        return True

    def update(self, name: str) -> InstallResult:
        """更新一个 skill 到最新版。"""
        existing = self.get_installed(name)
        if not existing:
            return InstallResult(success=False, error=f"Skill '{name}' not installed.")

        # 先卸载再重新安装
        old_source = existing.source
        self.uninstall(name)

        if old_source == "pypi":
            return self._install_pypi(name)
        elif old_source == "github":
            return self._install_github(existing.repository or f"https://github.com/{name}")
        elif old_source == "local":
            return self._install_local(
                Path(existing.install_path), Path(existing.install_path) / "skill.yaml"
            )

        return InstallResult(success=False, error=f"Unknown source: {old_source}")

    def register(self, manifest: SkillManifest, force: bool = False) -> InstallResult | None:
        """公开注册接口: 直接将 SkillManifest 写入 registry (不复制文件)。

        用于 importer.import_skill() / import_all() 等场景。
        与 install() 的区别: install 会复制/下载源文件，register 只写索引。
        """
        existing = self.get_installed(manifest.name)
        if existing and not force:
            return InstallResult(
                success=False,
                error=f"Skill '{manifest.name}' already installed. Use force=True to overwrite.",
            )
        if existing and force:
            self.uninstall(manifest.name)

        self._register_manifest(manifest)
        return InstallResult(success=True, manifest=manifest)

    def stats(self) -> dict:
        """市场统计。"""
        installed = self.list_installed()
        by_format = {}
        for m in installed:
            fmt = m.format.value
            by_format[fmt] = by_format.get(fmt, 0) + 1
        return {
            "total": len(installed),
            "by_format": by_format,
            "market_dir": str(MARKET_DIR),
        }

    def _check_duplicate(self, name: str) -> InstallResult | None:
        """如果 skill 已安装，返回失败结果；否则返回 None。"""
        existing = self.get_installed(name)
        if existing:
            return InstallResult(
                success=False,
                error=f"Skill '{name}' already installed (v{existing.version}). Use 'marketplace update {name}' to upgrade.",  # noqa: E501
            )
        return None

    def _install_pypi(self, name: str) -> InstallResult:
        """从 PyPI 安装 agentos-skill-<name>。"""
        pkg = f"{PYPI_SKILL_PREFIX}{name}"
        try:
            r = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    pkg,
                    "--quiet",
                    "--disable-pip-version-check",
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if r.returncode != 0:
                return InstallResult(success=False, error=f"pip install failed: {r.stderr[:200]}")
        except subprocess.TimeoutExpired:
            return InstallResult(success=False, error="pip install timed out")

        # 查找安装后的包位置，读取 manifest
        manifest = self._find_package_manifest(pkg)
        if not manifest:
            # 没有 manifest 的 PyPI 包也注册为 generic skill
            manifest = SkillManifest(
                name=name,
                version="?",
                description=f"PyPI package: {pkg}",
                format=SkillFormat.GENERIC,
                source="pypi",
            )
        manifest.source = "pypi"

        # 复制到 skills 目录
        self._copy_to_skills(name, manifest)

        # 注册
        self._register_manifest(manifest)
        return InstallResult(
            success=True,
            manifest=manifest,
            install_type="pypi_install",
            pypi_package=pkg,
        )

    def _install_local(self, local_path: Path, manifest_file: Path) -> InstallResult:
        """从本地目录安装。"""
        raw = manifest_file.read_text(encoding="utf-8")
        if manifest_file.suffix in (".yaml", ".yml"):
            import yaml

            data = yaml.safe_load(raw) or {}
        else:
            data = json.loads(raw)

        manifest = SkillManifest.from_dict(data, source="local", install_path=str(local_path))
        name = manifest.name or local_path.name

        dup = self._check_duplicate(name)
        if dup:
            return dup

        # 安装依赖
        deps = self._install_deps(manifest)

        # 复制到 skills 目录
        dest = SKILLS_DIR / name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(local_path, dest)

        manifest.install_path = str(dest)
        manifest.source = "local"
        self._register_manifest(manifest)

        return InstallResult(
            success=True,
            manifest=manifest,
            install_type="local_copy",
            dep_installed=deps,
        )

    def _install_github(self, url: str) -> InstallResult:
        """从 GitHub 克隆安装。"""
        name = url.rstrip("/").split("/")[-1].replace(".git", "")
        dest = SKILLS_DIR / name

        if dest.exists():
            shutil.rmtree(dest)

        try:
            r = subprocess.run(
                ["git", "clone", "--depth=1", url, str(dest)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if r.returncode != 0:
                return InstallResult(success=False, error=f"git clone failed: {r.stderr[:200]}")
        except FileNotFoundError:
            return InstallResult(success=False, error="git not found. Install git first.")
        except subprocess.TimeoutExpired:
            return InstallResult(success=False, error="git clone timed out")

        # 查找 manifest 文件
        manifest_file = None
        for fname in ("skill.yaml", "skill.json", "manifest.yaml", "manifest.json"):
            candidate = dest / fname
            if candidate.exists():
                manifest_file = candidate
                break

        if manifest_file:
            raw = manifest_file.read_text(encoding="utf-8")
            if manifest_file.suffix in (".yaml", ".yml"):
                import yaml

                data = yaml.safe_load(raw)
            else:
                data = json.loads(raw)
            manifest = SkillManifest.from_dict(data, source="github", install_path=str(dest))
        else:
            manifest = SkillManifest(
                name=name,
                version="0.1.0",
                description=f"GitHub skill: {url}",
                format=SkillFormat.GENERIC,
                source="github",
                install_path=str(dest),
                repository=url,
            )

        manifest.source = "github"
        manifest.repository = url
        if not manifest.name:
            manifest.name = name

        deps = self._install_deps(manifest)
        self._register_manifest(manifest)

        return InstallResult(
            success=True,
            manifest=manifest,
            install_type="git_clone",
            dep_installed=deps,
        )

    def _install_deps(self, manifest: SkillManifest) -> list[str]:
        """安装 skill 的 pip 依赖，返回成功安装的包名列表。"""
        installed = []
        for dep in manifest.dependencies:
            try:
                subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "pip",
                        "install",
                        dep,
                        "--quiet",
                        "--disable-pip-version-check",
                    ],
                    capture_output=True,
                    timeout=60,
                )
                installed.append(dep)
            except Exception:
                pass
        return installed

    def _find_package_manifest(self, pkg_name: str) -> SkillManifest | None:
        """从已安装的 PyPI 包中查找 manifest。"""
        try:
            r = subprocess.run(
                [sys.executable, "-m", "pip", "show", "-f", pkg_name],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if r.returncode != 0:
                return None

            # 找 Location 行
            location = ""
            for line in r.stdout.split("\n"):
                if line.startswith("Location:"):
                    location = line.split(":", 1)[1].strip()
                    break

            if not location:
                return None

            # 尝试常见 manifest 路径
            pkg_name_clean = pkg_name.replace("-", "_")
            candidates = [
                Path(location) / pkg_name_clean / "skill.yaml",
                Path(location) / pkg_name_clean / "skill.json",
                Path(location) / pkg_name_clean / "manifest.yaml",
                Path(location) / pkg_name_clean / "manifest.json",
            ]
            for p in candidates:
                if p.exists():
                    raw = p.read_text(encoding="utf-8")
                    if p.suffix in (".yaml", ".yml"):
                        import yaml

                        data = yaml.safe_load(raw)
                    else:
                        data = json.loads(raw)
                    return SkillManifest.from_dict(data, source="pypi")
        except Exception:
            pass
        return None

    def _copy_to_skills(self, name: str, manifest: SkillManifest):
        """确保 skill 源文件在 skills 目录有一份。"""
        dest = SKILLS_DIR / name
        dest.mkdir(parents=True, exist_ok=True)
        manifest_path = dest / "manifest.yaml"
        import yaml

        manifest_path.write_text(
            yaml.dump(
                manifest.to_dict(), allow_unicode=True, default_flow_style=False, sort_keys=False
            ),
            encoding="utf-8",
        )

    def _register_manifest(self, manifest: SkillManifest):
        """将 manifest 注册到 installed.json。"""
        data = self._load_installed()
        # 去重
        data["skills"] = [s for s in data.get("skills", []) if s.get("name") != manifest.name]
        entry = manifest.to_dict()
        entry["installed_at"] = time.time()
        data["skills"].append(entry)
        self._save_installed(data)

    def _load_installed(self) -> dict:
        MARKET_DIR.mkdir(parents=True, exist_ok=True)
        if not INSTALLED_JSON.exists():
            return {"version": "1.0", "skills": []}
        try:
            return json.loads(INSTALLED_JSON.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, Exception):
            return {"version": "1.0", "skills": []}

    def _save_installed(self, data: dict):
        MARKET_DIR.mkdir(parents=True, exist_ok=True)
        INSTALLED_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def _ensure_dirs(self):
        MARKET_DIR.mkdir(parents=True, exist_ok=True)
        SKILLS_DIR.mkdir(parents=True, exist_ok=True)
