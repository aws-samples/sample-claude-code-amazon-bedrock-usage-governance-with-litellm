"""
claude-chat-app/utils/chat_config_loader.py

LiteLLM config reader for the Claude Chat App — model access and budget info.

What it does:
  - Fetches the list of models that a user's API key is permitted to access by
    calling /key/info (key-specific models) and falling back to /models (all
    proxy models) if no key-specific list is set.
  - Fetches budget and rate-limit info for the currently logged-in user across
    three levels in priority order:
        1. Key level   — budget set directly on the API key.
        2. User level  — budget set on the LiteLLM user record (/user/info).
        3. Team level  — budget set on the user's team (/team/info).
    Returns the first non-null budget found, tagged with its level so the UI
    can display "Set at: user level" etc.
  - Caches all API responses for 5 minutes (CACHE_TTL) to avoid hammering the
    proxy on every Streamlit interaction and to stay within LiteLLM's own rate
    limits for admin endpoints.
  - All API calls use the LITELLM_MASTER_KEY so the chat app can read user/team
    budget data without the end-user needing admin access.

Model display utilities:
  get_display_name(alias)                     — "claude-sonnet-4-6" → "Claude Sonnet 4.6"
  get_model_alias(display_name, models_list)  — reverse mapping for the selectbox.

Main class:  ChatConfig (instantiated as a Streamlit @cache_resource singleton).
Entry point: get_chat_config() — returns the shared singleton.

Environment variables consumed:
  LITELLM_BASE_URL    — proxy address (default: http://litellm:4000).
  LITELLM_MASTER_KEY  — master key for /key/info, /user/info, /team/info calls.
"""

import os
import time
import requests
import streamlit as st


LITELLM_BASE_URL = os.getenv("LITELLM_BASE_URL", "http://litellm:4000")
LITELLM_MASTER_KEY = os.getenv("LITELLM_MASTER_KEY", "")

# Cache duration in seconds (5 minutes)
CACHE_TTL = 300


# ===== DISPLAY NAME MAPPING =====
MODEL_DISPLAY_NAMES = {
    "claude-sonnet-4-6": "Claude Sonnet 4.6",
    "claude-haiku-4-5": "Claude Haiku 4.5",
    "claude-haiku-4-5-20251001": "Claude Haiku 4.5",
    "claude-opus-4-8": "Claude Opus 4.8",
}


def get_display_name(model_alias):
    """Convert model alias to friendly display name."""
    return MODEL_DISPLAY_NAMES.get(model_alias, model_alias)


def get_model_alias(display_name, available_models):
    """Convert display name back to model alias."""
    for model in available_models:
        if get_display_name(model) == display_name:
            return model
    return available_models[0] if available_models else ""


class ChatConfig:
    """Manages LiteLLM config with caching to prevent rate limiting."""

    def __init__(self):
        self._model_cache = {}
        self._budget_cache = {}

    # ============================================================
    # MODEL FETCHING
    # ============================================================

    def get_user_allowed_models(self, api_key):
        """
        Get models allowed for this user's API key.
        Checks key-specific models first, then falls back to all models.
        Caches result for CACHE_TTL seconds.
        """
        if not api_key:
            return []

        # Check cache
        cache_key = "models_" + api_key[:10]
        cached = self._model_cache.get(cache_key)
        if cached and (time.time() - cached["time"]) < CACHE_TTL:
            return cached["models"]

        # Fetch from LiteLLM API using MASTER KEY
        models = self._fetch_models(api_key)

        # Update cache only if we got results
        if models:
            self._model_cache[cache_key] = {
                "models": models,
                "time": time.time()
            }

        return models

    def _fetch_models(self, api_key):
        """Fetch available models using master key."""
        try:
            auth_key = LITELLM_MASTER_KEY if LITELLM_MASTER_KEY else api_key
            headers = {"Authorization": "Bearer " + auth_key}

            # Step 1: Try to get user-specific models from /key/info
            try:
                response = requests.get(
                    LITELLM_BASE_URL + "/key/info",
                    params={"key": api_key},
                    headers=headers,
                    timeout=10,
                )
                if response.status_code == 200:
                    data = response.json()
                    key_info = data.get("info", {})
                    if not key_info:
                        key_info = data.get("key", {})
                    user_models = key_info.get("models", [])
                    if user_models:
                        return user_models
            except Exception:
                pass

            # Step 2: Fallback - get ALL models from /models endpoint
            response = requests.get(
                LITELLM_BASE_URL + "/models",
                headers=headers,
                timeout=10,
            )

            if response.status_code == 200:
                data = response.json()
                model_list = data.get("data", [])
                models = []
                for model in model_list:
                    model_id = model.get("id", "")
                    if model_id:
                        models.append(model_id)
                return models

            return []

        except Exception:
            return []

    # ============================================================
    # BUDGET FETCHING (Key + User + Team levels)
    # ============================================================

    def get_user_budget_info(self, api_key):
        """
        Get budget and rate limit info.
        Checks KEY level first, then USER level, then TEAM level.
        Caches result for CACHE_TTL seconds.
        """
        if not api_key:
            return {}

        # Check cache
        cache_key = "budget_" + api_key[:10]
        cached = self._budget_cache.get(cache_key)
        if cached and (time.time() - cached["time"]) < CACHE_TTL:
            return cached["info"]

        # Fetch from API
        info = self._fetch_budget(api_key)

        # Update cache
        self._budget_cache[cache_key] = {
            "info": info,
            "time": time.time()
        }

        return info

    def _fetch_budget(self, api_key):
        """
        Fetch budget info - checks multiple levels:
        1. Key level (per-key budget)
        2. User level (per-user budget)
        3. Team level (per-team budget)
        Returns first non-null budget found.
        """
        try:
            auth_key = LITELLM_MASTER_KEY if LITELLM_MASTER_KEY else api_key
            headers = {"Authorization": "Bearer " + auth_key}

            # Get key info
            response = requests.get(
                LITELLM_BASE_URL + "/key/info",
                params={"key": api_key},
                headers=headers,
                timeout=10,
            )

            if response.status_code != 200:
                return {}

            data = response.json()
            key_info = data.get("info", {})
            if not key_info:
                key_info = data.get("key", {})

            # Extract key-level budget
            max_budget = key_info.get("max_budget")
            spend = key_info.get("spend", 0)
            tpm_limit = key_info.get("tpm_limit")
            rpm_limit = key_info.get("rpm_limit")

            # If key has budget set, use it
            if max_budget is not None:
                remaining = max_budget - spend
                return {
                    "max_budget": max_budget,
                    "spend": spend,
                    "remaining": remaining,
                    "tpm_limit": tpm_limit,
                    "rpm_limit": rpm_limit,
                    "budget_level": "key",
                }

            # No key-level budget - check USER level
            user_id = key_info.get("user_id", "")
            if user_id:
                user_budget = self._fetch_user_budget(user_id, headers)
                if user_budget and user_budget.get("max_budget") is not None:
                    # Merge: prefer key-level rate limits if set
                    user_budget["tpm_limit"] = tpm_limit or user_budget.get("tpm_limit")
                    user_budget["rpm_limit"] = rpm_limit or user_budget.get("rpm_limit")
                    user_budget["budget_level"] = "user"
                    return user_budget

            # No user-level budget - check TEAM level
            team_id = key_info.get("team_id", "")
            if team_id:
                team_budget = self._fetch_team_budget(team_id, headers)
                if team_budget and team_budget.get("max_budget") is not None:
                    team_budget["tpm_limit"] = tpm_limit or team_budget.get("tpm_limit")
                    team_budget["rpm_limit"] = rpm_limit or team_budget.get("rpm_limit")
                    team_budget["budget_level"] = "team"
                    return team_budget

            # No budget set at any level
            return {
                "max_budget": None,
                "spend": spend,
                "remaining": None,
                "tpm_limit": tpm_limit,
                "rpm_limit": rpm_limit,
                "budget_level": None,
            }

        except Exception:
            return {}

    def _fetch_user_budget(self, user_id, headers):
        """Fetch user-level budget from /user/info."""
        try:
            response = requests.get(
                LITELLM_BASE_URL + "/user/info",
                params={"user_id": user_id},
                headers=headers,
                timeout=10,
            )

            if response.status_code == 200:
                data = response.json()

                # LiteLLM /user/info response can vary in structure
                user_info = data.get("user_info", {})
                if not user_info:
                    user_info = data

                max_budget = user_info.get("max_budget")
                spend = user_info.get("spend", 0)
                remaining = None
                if max_budget is not None:
                    remaining = max_budget - spend

                return {
                    "max_budget": max_budget,
                    "spend": spend,
                    "remaining": remaining,
                    "tpm_limit": user_info.get("tpm_limit"),
                    "rpm_limit": user_info.get("rpm_limit"),
                }

            return None

        except Exception:
            return None

    def _fetch_team_budget(self, team_id, headers):
        """Fetch team-level budget from /team/info."""
        try:
            response = requests.get(
                LITELLM_BASE_URL + "/team/info",
                params={"team_id": team_id},
                headers=headers,
                timeout=10,
            )

            if response.status_code == 200:
                data = response.json()

                team_info = data.get("team_info", {})
                if not team_info:
                    team_info = data

                max_budget = team_info.get("max_budget")
                spend = team_info.get("spend", 0)
                remaining = None
                if max_budget is not None:
                    remaining = max_budget - spend

                return {
                    "max_budget": max_budget,
                    "spend": spend,
                    "remaining": remaining,
                    "tpm_limit": team_info.get("tpm_limit"),
                    "rpm_limit": team_info.get("rpm_limit"),
                }

            return None

        except Exception:
            return None


# ===== SINGLETON INSTANCE =====
@st.cache_resource
def get_chat_config():
    """Get or create cached ChatConfig instance."""
    return ChatConfig()