"""
Dataclass for viewer configurations.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ViewerConfig:
    mode: str = "live"
    """Viewer mode: 'live' or 'replay'."""

    host: str = "127.0.0.1"
    """Host address for the ZMQ subscriber."""
    
    port: int = 6666
    """Port number for the ZMQ subscriber."""
    
    data_path: Optional[str] = None
    """Path to the data folder for replay mode."""
    