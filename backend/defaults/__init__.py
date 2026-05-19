"""Python defaults replacing bundled JSON files.

SQLite is the single source of truth at runtime. These constants seed
fresh databases and replace all JSON template files previously shipped
under /app and /backend.
"""

from .audio_language_defaults import DEFAULT_AUDIO_LANGUAGES
from .audio_codec_defaults import DEFAULT_AUDIO_CODEC_MAPPING
from .genre_defaults import DEFAULT_GENRE_MAPPING
from .provider_defaults import DEFAULT_PROVIDERS, DEFAULT_PROVIDER_LOGOS
from .config_defaults import DEFAULT_CONFIG
from .recommendation_defaults import DEFAULT_RECOMMENDATION_RULES
from .score_defaults import DEFAULT_SCORE_CONFIGURATION

__all__ = [
    "DEFAULT_AUDIO_LANGUAGES",
    "DEFAULT_AUDIO_CODEC_MAPPING",
    "DEFAULT_GENRE_MAPPING",
    "DEFAULT_PROVIDERS",
    "DEFAULT_PROVIDER_LOGOS",
    "DEFAULT_CONFIG",
    "DEFAULT_RECOMMENDATION_RULES",
    "DEFAULT_SCORE_CONFIGURATION",
]
