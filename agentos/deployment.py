from dataclasses import dataclass


@dataclass
class DockerConfig:
    image: str = ""


@dataclass
class ComposeService:
    name: str = ""


@dataclass
class ComposeConfig:
    version: str = "3.8"
