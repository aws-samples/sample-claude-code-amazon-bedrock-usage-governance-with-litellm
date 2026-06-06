"""
litellm-admin-dashboard/utils/litellm_client.py

HTTP client wrapper for the LiteLLM Proxy REST API.

What it does:
  - Provides a typed Python interface over the raw LiteLLM HTTP endpoints so
    every dashboard page can call simple methods (create_user, reset_team_budget,
    etc.) without hand-crafting requests or parsing error formats.
  - Authenticates every call with the LITELLM_MASTER_KEY, giving admin-level
    access to all user, team, model, and spend operations.
  - Normalises API error responses into clean Python exceptions with a readable
    message, so pages only need a single try/except around each call.

Covered API surface:
  Users   — list, create, update, delete, reset spend, get info.
  Keys    — generate API keys for users.
  Teams   — list, create, update, delete, reset spend, get info,
             add/remove members.
  Models  — list configured models, add new Bedrock model.
  Spend   — global spend total, per-user spend logs with date filtering.

Environment variables consumed:
  LITELLM_BASE_URL    — proxy address (default: http://litellm:4000).
  LITELLM_MASTER_KEY  — admin API key for master-level access.

Design note: spend resets intentionally carry NO budget_duration, enforcing
the manual-reset-only policy: admins must explicitly zero out user/team spend.
"""
import os
import requests
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

class LiteLLMClient:
    """Client for interacting with LiteLLM Proxy API."""

    def __init__(self):
        self.base_url = os.environ.get("LITELLM_BASE_URL", "http://litellm:4000")
        self.master_key = os.environ.get("LITELLM_MASTER_KEY", "")
        self.headers = {
            "Authorization": f"Bearer {self.master_key}",
            "Content-Type": "application/json"
        }

    def _request(self, method: str, endpoint: str, data: dict = None) -> Any:
        """Make HTTP request to LiteLLM API."""
        url = f"{self.base_url}{endpoint}"
        try:
            if method == "GET":
                response = requests.get(url, headers=self.headers, params=data, timeout=30)
            elif method == "POST":
                response = requests.post(url, headers=self.headers, json=data, timeout=30)
            elif method == "PUT":
                response = requests.put(url, headers=self.headers, json=data, timeout=30)
            elif method == "DELETE":
                response = requests.delete(url, headers=self.headers, json=data, timeout=30)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            error_detail = ""
            try:
                error_detail = e.response.json().get("error", str(e))
            except Exception:
                error_detail = str(e)
            raise Exception(f"LiteLLM API error: {error_detail}")
        except requests.exceptions.ConnectionError:
            raise Exception(f"Cannot connect to LiteLLM at {self.base_url}. Is the proxy running?")
        except requests.exceptions.Timeout:
            raise Exception("LiteLLM API request timed out.")

    # ==================== USER OPERATIONS ====================

    def list_users(self) -> List[Dict]:
        """Get all users."""
        result = self._request("GET", "/user/list")
        if isinstance(result, list):
            return result
        return result.get("users", result.get("data", []))

    def create_user(self, user_id: str, user_email: str = None,
                    max_budget: float = None, tpm_limit: int = None,
                    rpm_limit: int = None, allowed_models: List[str] = None,
                    team_id: str = None) -> Dict:
        """Create a new user (NO budget_duration - admin manual reset only)."""
        data = {"user_id": user_id}
        if user_email:
            data["user_email"] = user_email
        if max_budget is not None:
            data["max_budget"] = max_budget
        if tpm_limit is not None:
            data["tpm_limit"] = tpm_limit
        if rpm_limit is not None:
            data["rpm_limit"] = rpm_limit
        if allowed_models:
            data["models"] = allowed_models
        if team_id:
            data["team_id"] = team_id
        # NOTE: No budget_duration - spend never auto-resets
        return self._request("POST", "/user/new", data)

    def update_user(self, user_id: str, max_budget: float = None,
                    tpm_limit: int = None, rpm_limit: int = None,
                    models: List[str] = None) -> Dict:
        """Update user settings."""
        data = {"user_id": user_id}
        if max_budget is not None:
            data["max_budget"] = max_budget
        if tpm_limit is not None:
            data["tpm_limit"] = tpm_limit
        if rpm_limit is not None:
            data["rpm_limit"] = rpm_limit
        if models is not None:
            data["models"] = models
        return self._request("POST", "/user/update", data)

    def delete_user(self, user_ids: List[str]) -> Dict:
        """Delete one or more users."""
        return self._request("POST", "/user/delete", {"user_ids": user_ids})

    def reset_user_budget(self, user_id: str) -> Dict:
        """Reset user spend to $0 (manual admin action only)."""
        # 1. Reset user spend
        result = self._request("POST", "/user/update", {
            "user_id": user_id,
            "spend": 0,
            "budget_reset_at": datetime.now(timezone.utc).isoformat()
        })

        # 2. Also reset spend on all keys belonging to this user
        try:
            user_info = self._request("GET", "/user/info", {"user_id": user_id})
            keys = user_info.get("keys", [])
            for key in keys:
                token = key.get("token", key.get("key", ""))
                if token:
                    self._request("POST", "/key/update", {
                        "key": token,
                        "spend": 0
                    })
        except Exception:
            pass

        return result

    def get_user_info(self, user_id: str) -> Dict:
        """Get detailed info for a specific user."""
        return self._request("GET", "/user/info", {"user_id": user_id})

    # ==================== KEY OPERATIONS ====================

    def generate_key(self, user_id: str, key_alias: str = None,
                     max_budget: float = None, models: List[str] = None) -> Dict:
        """Generate an API key for a user."""
        data = {"user_id": user_id}
        if key_alias:
            data["key_alias"] = key_alias
        if max_budget is not None:
            data["max_budget"] = max_budget
        if models:
            data["models"] = models
        return self._request("POST", "/key/generate", data)

    # ==================== TEAM OPERATIONS ====================

    def list_teams(self) -> List[Dict]:
        """Get all teams."""
        result = self._request("GET", "/team/list")
        if isinstance(result, list):
            return result
        return result.get("teams", result.get("data", []))

    def create_team(self, team_alias: str, max_budget: float = None,
                    tpm_limit: int = None, rpm_limit: int = None,
                    allowed_models: List[str] = None) -> Dict:
        """Create a new team (NO budget_duration)."""
        data = {"team_alias": team_alias}
        if max_budget is not None:
            data["max_budget"] = max_budget
        if tpm_limit is not None:
            data["tpm_limit"] = tpm_limit
        if rpm_limit is not None:
            data["rpm_limit"] = rpm_limit
        if allowed_models:
            data["models"] = allowed_models
        # NOTE: No budget_duration - spend never auto-resets
        return self._request("POST", "/team/new", data)

    def update_team(self, team_id: str, max_budget: float = None,
                    tpm_limit: int = None, rpm_limit: int = None,
                    models: List[str] = None, spend: float = None) -> Dict:
        """Update team settings."""
        data = {"team_id": team_id}
        if max_budget is not None:
            data["max_budget"] = max_budget
        if tpm_limit is not None:
            data["tpm_limit"] = tpm_limit
        if rpm_limit is not None:
            data["rpm_limit"] = rpm_limit
        if models is not None:
            data["models"] = models
        if spend is not None:
            data["spend"] = spend
        return self._request("POST", "/team/update", data)

    def delete_team(self, team_id: str) -> Dict:
        """Delete a team."""
        return self._request("POST", "/team/delete", {"team_ids": [team_id]})

    def reset_team_budget(self, team_id: str) -> Dict:
        """Reset team spend to $0 (manual admin action only)."""
        result = self._request("POST", "/team/update", {
            "team_id": team_id,
            "spend": 0,
            "budget_reset_at": datetime.now(timezone.utc).isoformat()
        })
        return result

    def get_team_info(self, team_id: str) -> Dict:
        """Get detailed info for a specific team."""
        return self._request("GET", "/team/info", {"team_id": team_id})

    def add_team_member(self, team_id: str, user_id: str, role: str = "user") -> Dict:
        """Add a user as a member to a team."""
        data = {
            "team_id": team_id,
            "member": [{"role": role, "user_id": user_id}]
        }
        return self._request("POST", "/team/member_add", data)

    def remove_team_member(self, team_id: str, user_id: str) -> Dict:
        """Remove a user from a team."""
        data = {
            "team_id": team_id,
            "user_id": user_id
        }
        return self._request("POST", "/team/member_delete", data)

    # ==================== MODEL OPERATIONS ====================

    def list_models(self) -> Dict:
        """Get all configured models."""
        return self._request("GET", "/model/info")

    def add_model(self, model_name: str, litellm_params: Dict,
                  model_info: Dict = None) -> Dict:
        """Add a new model configuration."""
        data = {
            "model_name": model_name,
            "litellm_params": litellm_params
        }
        if model_info:
            data["model_info"] = model_info
        return self._request("POST", "/model/new", data)

    # ==================== SPEND/USAGE OPERATIONS ====================

    def get_global_spend(self) -> Dict:
        """Get total global spend."""
        return self._request("GET", "/global/spend")

    def get_spend_per_user(self, start_date: str = None, end_date: str = None) -> List[Dict]:
        """Get spend logs, optionally filtered by date range."""
        params = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        result = self._request("GET", "/spend/logs", params)
        if isinstance(result, list):
            return result
        return result.get("data", [])


