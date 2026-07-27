
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


@dataclass
class Config:
    """Central configuration for the ParchaAI extraction pipeline."""
    
    # =====================================================================
    # PATHS
    # =====================================================================
    # Base project directory
    project_root: Path = Path(__file__).parent.parent
    
    # Data directories
    datasets_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent / "drug_database")
    raw_images_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent / "data" / "raw_images")
    ground_truth_csv: Path = field(default_factory=lambda: Path(__file__).parent.parent / "data" / "labels" / "ground_truth.csv")
    drug_reference_db: Path = field(default_factory=lambda: Path(__file__).parent.parent / "drug_database" / "drug_reference_db.csv")
    
    # Output directories
    outputs_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent / "outputs")
    cache_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent / "cache")
    logs_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent / "logs")
    
    # =====================================================================
    # API KEYS & ENDPOINTS
    # =====================================================================
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    # Base REST endpoint for Gemini's generateContent call. The model name is
    # appended when building the final request URL.
    gemini_api_url: str = field(
        default_factory=lambda: os.getenv(
            "GEMINI_API_URL",
            "https://generativelanguage.googleapis.com/v1beta/models",
        )
    )

    groq_api_key: Optional[str] = field(
        default_factory=lambda: os.getenv("GROQ_API_KEY", None)
    )
    
    # OpenFDA API endpoint for global drug validation
    openfda_api_url: str = "https://api.fda.gov/drug/label.json"
    openfda_timeout: int = 10  # seconds
    
    # =====================================================================
    # PRIMARY MODEL (GOOGLE GEMINI VISION)
    # =====================================================================
    gemini_model_name: str = field(
        default_factory=lambda: os.getenv("GEMINI_MODEL_NAME", "gemini-3.1-flash-lite")
    )
    temperature: float = 0.0
    max_tokens: int = 3200
    gemini_max_retries: int = field(
        default_factory=lambda: int(os.getenv("GEMINI_MAX_RETRIES", "5"))
    )
    gemini_retry_base_delay: float = field(
        default_factory=lambda: float(os.getenv("GEMINI_RETRY_BASE_DELAY", "3.0"))
    )
    
    # =====================================================================
    # FALLBACK MODEL (GROQ VISION)
    # =====================================================================
    groq_model_name: str = field(
        default_factory=lambda: os.getenv(
            "GROQ_MODEL_NAME", "qwen/qwen3.6-27b"
        )
    )
    fallback_max_new_tokens: int = field(
        default_factory=lambda: int(os.getenv("FALLBACK_MAX_NEW_TOKENS", "4000"))
    )
    fallback_temperature: float = 0.0

    groq_reasoning_effort: str = field(
        default_factory=lambda: os.getenv("GROQ_REASONING_EFFORT", "none")
    )

    urdu_model: str = field(
        default_factory=lambda: os.getenv("URDU_MODEL", "llama-3.3-70b-versatile")
    )
    urdu_temperature: float = field(
        default_factory=lambda: float(os.getenv("URDU_TEMPERATURE", "0.1"))
    )
    urdu_max_tokens: int = field(
        default_factory=lambda: int(os.getenv("URDU_MAX_TOKENS", "220"))
    )
    urdu_tts_slow: bool = field(
        default_factory=lambda: os.getenv("URDU_TTS_SLOW", "false").lower()
        in {"1", "true", "yes"}
    )
    
    # =====================================================================
    # PIPELINE BEHAVIOR
    # =====================================================================
    confidence_threshold: float = 0.85
    
    # Enable/disable secondary verification pass
    enable_verification_pass: bool = True
    
    # Fuzzy matching thresholds
    fuzzy_match_threshold: int = 80  # RapidFuzz score for medicine NAME matching
    field_fuzzy_threshold: int = 85  # RapidFuzz score for field VALUE matching

    groq_max_retries: int = field(
        default_factory=lambda: int(os.getenv("GROQ_MAX_RETRIES", "8"))
    )
    groq_retry_base_delay: float = field(
        default_factory=lambda: float(os.getenv("GROQ_RETRY_BASE_DELAY", "3.0"))
    )
    inter_request_delay_seconds: float = field(
        default_factory=lambda: float(os.getenv("INTER_REQUEST_DELAY_SECONDS", "8"))
    )
    
    # Null-like tokens recognized as missing/unreadable data
    null_tokens: tuple = (
        "null", "none", "nan", "n/a", "na", "", "unread", "unknown"
    )
    
    # =====================================================================
    # CACHING
    # =====================================================================
    enable_cache: bool = True
    cache_ttl_hours: int = 24 * 7  # Cache validity: 7 days
    
    # =====================================================================
    # LOGGING
    # =====================================================================
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    log_format: str = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
    
    def __post_init__(self):
        """Create necessary directories and validate configuration."""
        # Create directories if they don't exist
        self.datasets_dir.mkdir(parents=True, exist_ok=True)
        self.raw_images_dir.mkdir(parents=True, exist_ok=True)
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
    
    def get_image_files(self) -> list[Path]:
        """Return sorted list of all image files in raw_images directory.
        
        Returns
        -------
        list[Path]
            Sorted list of image file paths (jpg, jpeg, png)
        """
        extensions = ("*.jpg", "*.jpeg", "*.png")
        files = []
        for ext in extensions:
            files.extend(self.raw_images_dir.glob(ext))
        return sorted(files)


# Global config instance (singleton pattern)
_config_instance: Optional[Config] = None


def get_config() -> Config:
    """Get or create the global configuration instance.
    
    Returns
    -------
    Config
        The global configuration object
    """
    global _config_instance
    if _config_instance is None:
        _config_instance = Config()
    return _config_instance


def reload_config() -> Config:
    """Force reload configuration from environment.
    
    Useful when environment variables have changed.
    
    Returns
    -------
    Config
        Newly created configuration object
    """
    global _config_instance
    load_dotenv(override=True)
    _config_instance = Config()
    return _config_instance


def setup_logging(level=None):
    """
    Setup application-wide logging configuration.
    
    Parameters
    ----------
    level : str or int, optional
        Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL) as string
        or logging constant (logging.DEBUG, logging.INFO, etc.) as int
        If None, uses config.log_level
    """
    import logging
    
    config = get_config()
    
    # Create logs directory
    config.logs_dir.mkdir(parents=True, exist_ok=True)
    
    # Determine log level
    if level is None:
        # Use config default
        log_level = getattr(logging, config.log_level.upper())
    elif isinstance(level, int):
        # Already an int (e.g., logging.DEBUG)
        log_level = level
    elif isinstance(level, str):
        # Convert string to int
        log_level = getattr(logging, level.upper())
    else:
        # Fallback
        log_level = logging.INFO
    
    # Configure root logger
    logging.basicConfig(
        level=log_level,
        format=config.log_format,
        handlers=[
            logging.StreamHandler(),  # Console output
            logging.FileHandler(
                config.logs_dir / "parcha_ai.log",
                encoding='utf-8'
            )
        ]
    )