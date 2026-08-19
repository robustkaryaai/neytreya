from dataclasses import dataclass

@dataclass(frozen=True)
class ProductManifest:
    """
    Defines the identity and capabilities of a RexyCore product.
    """
    id: str
    version: str
    protocol: str = "1.0"
