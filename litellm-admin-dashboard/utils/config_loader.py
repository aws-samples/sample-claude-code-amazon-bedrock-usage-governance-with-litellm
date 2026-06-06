"""
litellm-admin-dashboard/utils/config_loader.py

Single-source-of-truth reader for litellm_config.yaml.

What it does:
  - Loads and in-process caches litellm_config.yaml so every page reads the
    same parsed object without hitting the filesystem on every request.
  - Exposes helper functions that extract specific slices of the config so
    page code never has to navigate the YAML structure directly.
  - Validates dashboard defaults against the live model_list so stale
    references in dashboard_settings don't cause runtime surprises.

Key functions:
  get_allowed_models()       — list of all model names from model_list.
  get_default_user_models()  — default model whitelist for new users.
  get_default_team_models()  — default model whitelist for new teams.
  get_defaults()             — budget/TPM/RPM defaults for new users & teams.
  get_model_reference()      — pricing + limit metadata for Model Management page.
  get_aws_regions()          — region list for the Add Model dropdown.
  reload_config()            — force re-read (useful after a hot config change).

Config file location: the project root config.yaml (mounted into the container
from litellm_config.yaml via the docker-compose volume).
"""
import yaml
import os
from typing import List, Dict, Any

# Path to the single config file
CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "config.yaml"
)

_config_cache = None


def _load_config() -> Dict[str, Any]:
    """Load and cache the config file."""
    global _config_cache
    if _config_cache is None:
        try:
            with open(CONFIG_PATH, "r") as f:
                _config_cache = yaml.safe_load(f)
        except FileNotFoundError:
            raise FileNotFoundError(
                f"Config file not found at {CONFIG_PATH}. "
                f"Ensure litellm_config.yaml exists in the project root."
            )
        except yaml.YAMLError as e:
            raise ValueError(f"Error parsing litellm_config.yaml: {e}")
    return _config_cache


def reload_config():
    """Force reload config (useful if config changes at runtime)."""
    global _config_cache
    _config_cache = None
    return _load_config()


def get_allowed_models() -> List[str]:
    """
    Auto-extract all model names from model_list.
    No need to maintain a separate list — derived directly from model_list.
    """
    config = _load_config()
    model_list = config.get("model_list", [])
    return [m["model_name"] for m in model_list if "model_name" in m]


def get_default_user_models() -> List[str]:
    """Get default models for new users."""
    config = _load_config()
    dashboard = config.get("dashboard_settings", {})
    defaults = dashboard.get("default_user_models", [])
    # Validate against actual model_list
    available = get_allowed_models()
    return [m for m in defaults if m in available] or available


def get_default_team_models() -> List[str]:
    """Get default models for new teams."""
    config = _load_config()
    dashboard = config.get("dashboard_settings", {})
    defaults = dashboard.get("default_team_models", [])
    # Validate against actual model_list
    available = get_allowed_models()
    return [m for m in defaults if m in available] or available


def get_defaults() -> Dict[str, Any]:
    """Get all default budget/limit settings."""
    config = _load_config()
    dashboard = config.get("dashboard_settings", {})
    return dashboard.get("defaults", {
        "user_budget": 50.0,
        "user_tpm": 200000,
        "user_rpm": 60,
        "team_budget": 500.0,
        "team_tpm": 500000,
        "team_rpm": 100,
    })


def get_model_reference() -> List[Dict[str, Any]]:
    """
    Build model reference info from model_list.
    Used in Model Management page to show available models.
    """
    config = _load_config()
    model_list = config.get("model_list", [])

    reference = []
    for model in model_list:
        model_info = model.get("model_info", {})
        litellm_params = model.get("litellm_params", {})

        input_cost = model_info.get("input_cost_per_token", 0)
        output_cost = model_info.get("output_cost_per_token", 0)

        reference.append({
            "name": model.get("model_name", ""),
            "bedrock_model_id": litellm_params.get("model", ""),
            "input_cost_per_token": input_cost,
            "output_cost_per_token": output_cost,
            "input_cost_per_million": input_cost * 1_000_000,
            "output_cost_per_million": output_cost * 1_000_000,
            "max_tokens": model_info.get("max_tokens", "N/A"),
            "max_input_tokens": model_info.get("max_input_tokens", "N/A"),
            "region": litellm_params.get("aws_region_name", "us-east-1"),
        })

    return reference


def get_aws_regions() -> List[str]:
    """Get available AWS regions for Add Model form."""
    config = _load_config()
    dashboard = config.get("dashboard_settings", {})
    return dashboard.get("aws_regions", ["us-east-1", "us-west-2"])


