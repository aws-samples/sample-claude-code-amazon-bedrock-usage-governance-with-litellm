"""
litellm-admin-dashboard/auth.py

Handles authentication for the Admin Dashboard.

What it does:
  - Renders a username + password login form at the top of every page.
  - Validates credentials using constant-time comparison (hmac.compare_digest)
    against the user map stored in Streamlit secrets (secrets.toml → auth.users).
  - Stores the authenticated flag, username, and login timestamp in Streamlit
    session state so every page can gate access with a single check_password() call.
  - Automatically expires sessions after 8 hours and forces re-login.
  - Provides a logout button rendered in the sidebar so admins can end their
    session from any page.

Key functions:
  check_password()  — call at the top of every page; returns True if authenticated.
  logout_button()   — call in the sidebar to render the "Logged in as / Logout" widget.

Credentials are stored in litellm-admin-dashboard/.streamlit/secrets.toml:
  [auth.users]
  admin = "your-password"
"""

import streamlit as st
import hmac
import time


def check_password():
    """
    Returns True if the user has entered a valid password.
    Place this at the TOP of your main app.py file.
    """

    def login_form():
        """Display the login form."""
        st.markdown(
            """
            <style>
            .login-container {
                max-width: 400px;
                margin: 0 auto;
                padding: 2rem;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("---")
        st.markdown("### 🔐 Claude Code Admin Portal")
        st.markdown("Please enter your credentials to continue.")

        with st.form("login_form"):
            username = st.text_input("Username", placeholder="Enter username")
            password = st.text_input(
                "Password", type="password", placeholder="Enter password"
            )
            submitted = st.form_submit_button("Login", use_container_width=True)

            if submitted:
                authenticate(username, password)

    def authenticate(username, password):
        """Validate credentials against secrets."""
        valid_users = st.secrets.get("auth", {}).get("users", {})

        if username in valid_users and hmac.compare_digest(
            password, valid_users[username]
        ):
            st.session_state["authenticated"] = True
            st.session_state["username"] = username
            st.session_state["login_time"] = time.time()
            st.rerun()
        else:
            st.session_state["authenticated"] = False
            st.error("❌ Invalid username or password")

    # Check if already authenticated
    if st.session_state.get("authenticated", False):
        # Optional: Session timeout (8 hours)
        login_time = st.session_state.get("login_time", 0)
        if time.time() - login_time > 28800:  # 8 hours
            st.session_state["authenticated"] = False
            st.warning("⏰ Session expired. Please login again.")
            login_form()
            return False
        return True

    # Not authenticated — show login form
    login_form()
    return False


def logout_button():
    """Display a logout button in the sidebar."""
    with st.sidebar:
        st.markdown(f"👤 Logged in as: **{st.session_state.get('username', 'admin')}**")
        if st.button("🚪 Logout", use_container_width=True):
            st.session_state["authenticated"] = False
            st.session_state["username"] = None
            st.rerun()

