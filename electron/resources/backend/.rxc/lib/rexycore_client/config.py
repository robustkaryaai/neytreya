import os
import json
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

@dataclass
class RuntimeConfig:
    device_slug: str
    hub_uri: str
    runtime_version: str
    protocol_version: str
    environment: str

class ConfigLoader:
    """
    Automatically loads the global RexyCore configuration.
    The Runtime owns this config; products merely consume it.
    """
    DEFAULT_CONFIG_PATH = Path.home() / ".rexycore" / "config.json"
    
    @classmethod
    def load(cls) -> RuntimeConfig:
        if not cls.DEFAULT_CONFIG_PATH.exists():
            raise FileNotFoundError(
                f"RexyCore Runtime Configuration not found at {cls.DEFAULT_CONFIG_PATH}. "
                "Ensure the Runtime is installed and configured."
            )
            
        with open(cls.DEFAULT_CONFIG_PATH, "r") as f:
            data = json.load(f)
            
        return RuntimeConfig(
            device_slug=data["device_slug"],
            hub_uri=data.get("hub_uri", "ws://127.0.0.1:8080"),
            runtime_version=data.get("runtime_version", "1.0.0"),
            protocol_version=data.get("protocol_version", "1.0"),
            environment=data.get("environment", "production")
        )
