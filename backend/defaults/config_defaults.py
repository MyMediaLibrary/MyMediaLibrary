"""Default application configuration seeded into fresh databases."""

DEFAULT_CONFIG: dict = {
    "system": {
        "scan_cron": "0 3 * * *",
        "log_level": "INFO",
        "needs_onboarding": True,
        "inventory_enabled": False,
    },
    "folders": [],
    "enable_movies": True,
    "enable_series": True,
    "seerr": {
        "enabled": False,
        "url": "",
    },
    "providers_visible": [],
    "ui": {
        "synopsis_on_hover": False,
        "default_view": "grid",
        "default_sort": "title-asc",
        "theme": "dark",
        "accent_color": "#7c6aff",
    },
    "score": {
        "enabled": False,
    },
    "recommendations": {
        "enabled": False,
    },
    "media_probe": {
        "enabled": False,
        "mode": "compare",
        "workers": 4,
        "cache_enabled": True,
    },
}
