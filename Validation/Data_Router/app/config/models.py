"""Dataclass models for Data Router configuration."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Union


class SourceType(str, Enum):
    FILE = "file"
    TCP = "tcp"


class FramingType(str, Enum):
    LINE = "line"
    LENGTH_PREFIXED = "length_prefixed"
    RAW_BLOCK = "raw_block"


@dataclass
class DataInflowConfig:
    """Configuration for data inflow base directory."""
    base_dir: str = "DATA_INFLOW"


@dataclass
class ParserDestinationConfig:
    """Configuration for a downstream Data Parser endpoint."""
    name: str
    host: str = "127.0.0.1"
    port: int = 10001
    framing: str = "ndjson"  # "ndjson" or "length_prefixed"
    timeout_seconds: float = 5.0
    keep_alive: bool = True


@dataclass
class BaseSourceConfig:
    """Base source configuration."""
    name: str
    type: SourceType
    parser: str
    enabled: bool = True


@dataclass
class FileSourceConfig(BaseSourceConfig):
    """Configuration for file/folder input source."""
    folder: str = ""
    poll_interval_seconds: float = 1.0
    stability_window_seconds: float = 1.0
    file_patterns: List[str] = field(default_factory=lambda: ["*.csv", "*.txt", "*"])
    preserve_file: bool = False
    processed_folder: str = ""


@dataclass
class TCPSourceConfig(BaseSourceConfig):
    """Configuration for network TCP/IP input source."""
    remote_host: str = "127.0.0.1"
    remote_port: int = 0
    framing: FramingType = FramingType.LINE
    delimiter: str = "\n"
    max_line_length: int = 65536
    reconnect_initial_delay: float = 2.0
    reconnect_max_delay: float = 60.0
    reconnect_multiplier: float = 2.0


SourceConfig = Union[FileSourceConfig, TCPSourceConfig]


@dataclass
class RetryConfig:
    """Retry policy for delivery to parser endpoints."""
    max_attempts: int = 5
    initial_delay_seconds: float = 2.0
    max_delay_seconds: float = 60.0
    backoff_multiplier: float = 2.0


@dataclass
class QueueConfig:
    """Internal bounded queue configuration."""
    max_size: int = 10000
    worker_count: int = 4
    high_watermark_ratio: float = 0.8


@dataclass
class MonitoringConfig:
    """Configuration for service health and operational metrics."""
    enabled: bool = True
    http_host: str = "127.0.0.1"
    http_port: int = 8080


@dataclass
class StateConfig:
    """Configuration for local SQLite state storage."""
    db_path: str = "state/router_state.db"


@dataclass
class RouterConfig:
    """Master configuration for the Data Router Service."""
    data_inflow: DataInflowConfig = field(default_factory=DataInflowConfig)
    parser_destinations: Dict[str, ParserDestinationConfig] = field(default_factory=dict)
    sources: Dict[str, SourceConfig] = field(default_factory=dict)
    retry: RetryConfig = field(default_factory=RetryConfig)
    queue: QueueConfig = field(default_factory=QueueConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    state: StateConfig = field(default_factory=StateConfig)
