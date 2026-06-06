"""
claude-chat-app/auth.py

Authentication module for the Claude Chat App.

What it does:
  - Renders a three-field login form: username, password, and LiteLLM API key.
  - Validates username + password against the credentials in Streamlit secrets
    (secrets.toml → auth.users). The API key is not validated here — it is
    stored in session state and used by the chat app to make LiteLLM requests
    on behalf of the user, so any key accepted by LiteLLM is valid.
  - Stores the authenticated flag, username, API key, and login timestamp in
    Streamlit session state. The API key is then used by the chat page to query
    only the models and budget assigned to that key.
  - Automatically expires sessions after 8 hours and clears all session data
    (including chat history) on logout or expiry.
  - Provides a logout button for the sidebar that wipes the session cleanly.

Difference from admin auth (litellm-admin-dashboard/auth.py):
  This form collects the user's personal LiteLLM API key in addition to
  username/password. That key is passed to the OpenAI-compatible client so
  that LiteLLM enforces per-user budget and model restrictions for each chat
  request. The admin dashboard uses the master key and does not need this.

Credentials are stored in claude-chat-app/.streamlit/secrets.toml:
  [auth.users]
  alice = "password123"
"""

import streamlit as st
import time


# Session timeout: 8 hours (in seconds)
SESSION_TIMEOUT = 8 * 60 * 60


def check_password():
    """Returns True if the user has valid credentials."""

    # Already authenticated - check if session expired
    if st.session_state.get("authenticated"):
        login_time = st.session_state.get("login_time", 0)
        elapsed = time.time() - login_time

        if elapsed > SESSION_TIMEOUT:
            # Session expired - clear everything
            st.session_state["authenticated"] = False
            st.session_state["api_key"] = ""
            st.session_state["username"] = ""
            st.session_state["login_time"] = 0
            st.warning("⏰ Session expired. Please login again.")
            _show_login_form()
            return False

        # Session still valid
        return True

    # Not authenticated - show login form
    _show_login_form()
    return False


def _show_login_form():
    """Display the login form."""
    st.markdown("## 🤖 Claude Chat Portal")
    st.markdown("Please enter your credentials to continue.")

    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        api_key = st.text_input(
            "API Key",
            type="password",
            help="Your LiteLLM API key (provided by your admin)"
        )
        submitted = st.form_submit_button("Login", use_container_width=True)

    if submitted:
        if not username or not password or not api_key:
            st.error("❌ Please fill in all fields.")
            return

        # Validate username/password from secrets
        valid_users = st.secrets.get("auth", {}).get("users", {})

        if username in valid_users and valid_users[username] == password:
            # Login successful
            st.session_state["authenticated"] = True
            st.session_state["username"] = username
            st.session_state["api_key"] = api_key
            st.session_state["login_time"] = time.time()
            st.rerun()
        else:
            st.error("❌ Invalid username or password")


def logout_button():
    """Show logout button in sidebar."""
    username = st.session_state.get("username", "User")
    st.caption("Logged in as: **" + username + "**")

    if st.button("🚪 Logout", use_container_width=True):
        st.session_state["authenticated"] = False
        st.session_state["api_key"] = ""
        st.session_state["username"] = ""
        st.session_state["login_time"] = 0
        st.session_state["messages"] = []
        st.rerun()

