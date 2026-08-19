import os
import json
import time
import logging
import urllib.request
import urllib.error
import asyncio
import ssl
from pathlib import Path
from typing import Dict, Any

from .exceptions import DeviceVerificationFailedError

class DeviceVerifier:
    """
    Ensures that the product is running on a legitimate RexyCore installation.
    Integrates with the global backend and handles local offline caching.
    """
    CACHE_VALIDITY_SECONDS = 7 * 24 * 60 * 60  # 7 days offline grace period
    BACKEND_URL_TEMPLATE = "https://rk-ai-backend.onrender.com/device/check/{slug}"
    
    def __init__(self, config: "RuntimeConfig", logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.cache_dir = Path.home() / ".rexycore"
        self.cache_file = self.cache_dir / "device_cache.json"

    async def verify(self) -> None:
        """
        Main verification lifecycle. Raises DeviceVerificationFailedError on failure.
        """
        slug = self.config.device_slug
        if not slug:
            raise DeviceVerificationFailedError("Device slug missing from configuration.")

        # Execute blocking HTTP request in a thread pool to avoid blocking asyncio
        try:
            response = await asyncio.to_thread(self._check_backend, slug)
            if response.get("exists") is True:
                self.logger.info("Device verified successfully against backend.")
                self._update_cache(slug)
                return
            else:
                self.logger.error("Device verification rejected by backend.")
                raise DeviceVerificationFailedError("Backend rejected device legitimacy.")
                
        except (urllib.error.URLError, TimeoutError) as e:
            self.logger.warning(f"Backend unreachable for verification: {e}")
            if self._is_cache_valid(slug):
                self.logger.info("Operating in offline grace mode using cached verification.")
                return
            else:
                raise DeviceVerificationFailedError("Backend unreachable and no valid offline cache.")

    def _check_backend(self, slug: str) -> Dict[str, Any]:
        """Synchronous HTTP call to the backend."""
        url = self.BACKEND_URL_TEMPLATE.format(slug=slug)
        req = urllib.request.Request(url)
        # Use unverified context to fix macOS python cert issues
        context = ssl._create_unverified_context()
        # Using a short timeout to prevent blocking startup for too long if offline
        with urllib.request.urlopen(req, timeout=5.0, context=context) as response:
            data = response.read()
            return json.loads(data)

    def _update_cache(self, slug: str) -> None:
        """Update local cache with the latest verification timestamp."""
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            cache_data = {}
            if self.cache_file.exists():
                with open(self.cache_file, "r") as f:
                    cache_data = json.load(f)
                    
            cache_data[slug] = time.time()
            
            with open(self.cache_file, "w") as f:
                json.dump(cache_data, f)
        except Exception as e:
            self.logger.debug(f"Failed to write verification cache: {e}")

    def _is_cache_valid(self, slug: str) -> bool:
        """Check if the slug was successfully verified within the grace period."""
        if not self.cache_file.exists():
            return False
            
        try:
            with open(self.cache_file, "r") as f:
                cache_data = json.load(f)
                
            last_verified = cache_data.get(slug)
            if not last_verified:
                return False
                
            return (time.time() - last_verified) <= self.CACHE_VALIDITY_SECONDS
        except Exception as e:
            self.logger.debug(f"Failed to read verification cache: {e}")
            return False
