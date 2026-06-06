"""
custom_callback.py

CloudWatch audit logger — per-user API call tracking for the LiteLLM proxy.

What it does:
  - Implements a LiteLLM CustomLogger that fires on every proxied API call
    (success and failure, both streaming and non-streaming).
  - On each call, identifies the calling user by resolving the API key from
    a local in-memory cache (key hash → user_id) that refreshes every 5 minutes
    from the LiteLLM /key/list endpoint.
  - Writes a structured JSON log event to an AWS CloudWatch Logs stream named
    "user-{user_id}" inside the log group defined by CW_LOG_GROUP_NAME.
  - Each log record includes: timestamp, event type (success/failure), user_id,
    model name, token counts (prompt/completion/total), USD cost, and latency.
  - Auto-creates the CloudWatch log group and per-user log streams on first use.

Why per-user log streams:
  A single flat log stream would require expensive filtering to answer "what did
  user X do?" Separate streams make CloudWatch Insights queries, cost attribution,
  and security audits trivially scoped to a single user without cross-user noise.

Key resolution strategy:
  LiteLLM v1.88 does not reliably propagate user_id into callback kwargs.
  The logger works around this by maintaining a key_hash → user_id cache built
  from /key/list, then matching the last 10 characters of the bearer token seen
  in the request against that cache. If no match is found, "unknown" is used.

Environment variables consumed:
  CW_LOG_GROUP_NAME   — CloudWatch log group (default: /litellm/claude-code-usage).
  LITELLM_MASTER_KEY  — master key used to call /key/list for cache loading.
  AWS_REGION_NAME     — region for the CloudWatch Logs client (default: ap-south-1).

Registered in litellm_config.yaml as:
  litellm_settings:
    callbacks: custom_callback.proxy_handler_instance
"""
from litellm.integrations.custom_logger import CustomLogger
import boto3
import json
import time
import re
import os
import requests
from datetime import datetime
import traceback


class CloudWatchDetailedLogger(CustomLogger):
    def __init__(self):
        self.cw = boto3.client("logs", region_name="ap-south-1")
        self.log_group = "/litellm/claude-code-usage"
        self.master_key = os.environ.get(
            "LITELLM_MASTER_KEY",
            "sk-xxx-xxx"
        )
        self.base_url = "http://localhost:4000"
        self.key_user_cache = {}
        self._last_cache_refresh = 0
        self._ensure_log_group()
        # Cache loads on first request, not at startup (LiteLLM isn't ready yet)

    def _ensure_log_group(self):
        try:
            self.cw.create_log_group(logGroupName=self.log_group)
        except self.cw.exceptions.ResourceAlreadyExistsException:
            pass

    def _ensure_log_stream(self, stream_name):
        try:
            self.cw.create_log_stream(
                logGroupName=self.log_group,
                logStreamName=stream_name
            )
        except self.cw.exceptions.ResourceAlreadyExistsException:
            pass

    def _load_key_cache(self):
        """Load all keys and map key_hash -> user_id."""
        try:
            resp = requests.get(
                f"{self.base_url}/key/list",
                headers={"Authorization": f"Bearer {self.master_key}"},
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                # Handle different response formats
                if isinstance(data, list):
                    keys = data
                elif isinstance(data, dict):
                    keys = data.get("keys", data.get("data", []))
                else:
                    keys = []

                new_cache = {}
                for key_info in keys:
                    if not isinstance(key_info, dict):
                        continue
                    token = key_info.get("token", "")
                    user_id = key_info.get("user_id", "")
                    if token and user_id:
                        new_cache[token[-10:]] = user_id
                self.key_user_cache = new_cache
                self._last_cache_refresh = time.time()
                print(f"[CloudWatch] Loaded {len(self.key_user_cache)} key-to-user mappings")
            else:
                print(f"[CloudWatch] Key list returned: {resp.status_code}")
        except requests.exceptions.ConnectionError:
            pass  # Silent - LiteLLM not ready yet, will retry
        except requests.exceptions.ReadTimeout:
            pass  # Silent - LiteLLM not ready yet, will retry
        except Exception as e:
            print(f"[CloudWatch] Key cache error: {e}")

    def _refresh_cache_if_needed(self):
        """Refresh cache every 5 minutes or on first call."""
        now = time.time()
        if now - self._last_cache_refresh > 300:
            self._load_key_cache()

    def _put_log(self, stream_name, record):
        stream_name = re.sub(r'[^a-zA-Z0-9_\-/.]', '_', stream_name)[:512]
        self._ensure_log_stream(stream_name)
        try:
            self.cw.put_log_events(
                logGroupName=self.log_group,
                logStreamName=stream_name,
                logEvents=[
                    {
                        "timestamp": int(time.time() * 1000),
                        "message": json.dumps(record)
                    }
                ]
            )
        except Exception as e:
            print(f"[CloudWatch] Failed to put log: {e}")

    def _get_user_id(self, kwargs):
        """Extract user_id using key cache lookup."""
        # Refresh cache if stale
        self._refresh_cache_if_needed()

        # 1. Try standard metadata locations
        meta = kwargs.get("litellm_params", {}).get("metadata", {})
        for field in ["user_api_key_user_id", "user_id"]:
            val = meta.get(field)
            if val and val != "" and not val.startswith("{"):
                return val

        # 2. Try standard_logging_object
        slo = kwargs.get("standard_logging_object")
        if slo and isinstance(slo, dict):
            for field in ["end_user", "user"]:
                val = slo.get(field)
                if val and isinstance(val, str) and not val.startswith("{"):
                    return val
            slo_meta = slo.get("metadata", {})
            if isinstance(slo_meta, dict):
                val = slo_meta.get("user_api_key_user_id")
                if val and val != "":
                    return val
                api_key = slo_meta.get("user_api_key", "")
                if api_key and api_key[-10:] in self.key_user_cache:
                    return self.key_user_cache[api_key[-10:]]

        # 3. Try api_key in various locations and look up in cache
        litellm_params = kwargs.get("litellm_params", {})

        api_key = kwargs.get("api_key", "")
        if api_key and api_key[-10:] in self.key_user_cache:
            return self.key_user_cache[api_key[-10:]]

        api_key = litellm_params.get("api_key", "")
        if api_key and api_key[-10:] in self.key_user_cache:
            return self.key_user_cache[api_key[-10:]]

        api_key = meta.get("user_api_key", "")
        if api_key and api_key[-10:] in self.key_user_cache:
            return self.key_user_cache[api_key[-10:]]

        hidden = meta.get("hidden_params", {})
        if isinstance(hidden, dict):
            api_key = hidden.get("user_api_key", "")
            if api_key and api_key[-10:] in self.key_user_cache:
                return self.key_user_cache[api_key[-10:]]

        # 4. Check proxy_server_request for authorization header
        proxy_req = litellm_params.get("proxy_server_request", {})
        if isinstance(proxy_req, dict):
            headers = proxy_req.get("headers", {})
            if isinstance(headers, dict):
                auth = headers.get("authorization", "")
                if auth.startswith("Bearer "):
                    token = auth.replace("Bearer ", "")
                    if token[-10:] in self.key_user_cache:
                        return self.key_user_cache[token[-10:]]

        return "unknown"

    def log_success_event(self, kwargs, response_obj, start_time, end_time):
        """Handle ALL success events."""
        try:
            user_id = self._get_user_id(kwargs)
            usage = getattr(response_obj, "usage", None)

            record = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "event": "success",
                "user_id": user_id,
                "model": kwargs.get("model", ""),
                "total_tokens": usage.total_tokens if usage else 0,
                "prompt_tokens": usage.prompt_tokens if usage else 0,
                "completion_tokens": usage.completion_tokens if usage else 0,
                "cost_usd": round(kwargs.get("response_cost", 0) or 0, 6),
                "latency_seconds": round((end_time - start_time).total_seconds(), 3),
            }
            self._put_log(f"user-{user_id}", record)
        except Exception as e:
            print(f"[CloudWatch] log_success_event error: {e}")
            traceback.print_exc()

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        """Streaming success."""
        try:
            self.log_success_event(kwargs, response_obj, start_time, end_time)
        except Exception as e:
            print(f"[CloudWatch] async error: {e}")
            traceback.print_exc()

    def log_failure_event(self, kwargs, response_obj, start_time, end_time):
        """Handle failures."""
        try:
            user_id = self._get_user_id(kwargs)
            record = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "event": "failure",
                "user_id": user_id,
                "model": kwargs.get("model", ""),
                "error": str(kwargs.get("exception", "")),
                "latency_seconds": round((end_time - start_time).total_seconds(), 3),
            }
            self._put_log(f"user-{user_id}", record)
        except Exception as e:
            print(f"[CloudWatch] log_failure_event error: {e}")
            traceback.print_exc()

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        """Streaming failure."""
        try:
            self.log_failure_event(kwargs, response_obj, start_time, end_time)
        except Exception as e:
            print(f"[CloudWatch] async failure error: {e}")
            traceback.print_exc()


proxy_handler_instance = CloudWatchDetailedLogger()
