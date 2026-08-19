from __future__ import annotations

import logging
import time
from typing import Optional

import psutil

logger = logging.getLogger(__name__)

# Load-tier thresholds
_LOW_CPU = 40.0
_LOW_RAM = 70.0
_MED_CPU = 65.0
_MED_RAM = 85.0


class ResourceWatcher:
    """
    Monitors CPU, RAM, battery via psutil.
    Computes a load_tier (LOW / MEDIUM / HIGH) to gate other perception sources.
    """

    def get_resources(self) -> dict:
        """
        Return a dict compatible with PerceptionData resource fields:
        {cpu_percent, ram_percent, ram_available_gb, battery_percent,
         battery_plugged, load_tier}
        """
        cpu = self._get_cpu()
        ram = self._get_ram()
        battery = self._get_battery()
        load_tier = self._compute_tier(cpu, ram["percent"])

        return {
            "cpu_percent": cpu,
            "ram_percent": ram["percent"],
            "ram_available_gb": ram["available_gb"],
            "battery_percent": battery.get("percent"),
            "battery_plugged": battery.get("plugged"),
            "load_tier": load_tier,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_cpu() -> float:
        try:
            return psutil.cpu_percent(interval=0.3)
        except Exception as exc:
            logger.warning("CPU read error: %s", exc)
            return 0.0

    @staticmethod
    def _get_ram() -> dict:
        try:
            mem = psutil.virtual_memory()
            return {
                "percent": mem.percent,
                "available_gb": round(mem.available / (1024 ** 3), 2),
            }
        except Exception as exc:
            logger.warning("RAM read error: %s", exc)
            return {"percent": 0.0, "available_gb": 0.0}

    @staticmethod
    def _get_battery() -> dict:
        try:
            batt = psutil.sensors_battery()
            if batt is None:
                return {}
            return {
                "percent": round(batt.percent, 1),
                "plugged": batt.power_plugged,
            }
        except Exception:
            return {}

    @staticmethod
    def _compute_tier(cpu: float, ram: float) -> str:
        if cpu >= _MED_CPU or ram >= _MED_RAM:
            return "HIGH"
        if cpu >= _LOW_CPU or ram >= _LOW_RAM:
            return "MEDIUM"
        return "LOW"
