"""
litellm-admin-dashboard/app.py

Main entry point (home page) for the Claude Code Admin Dashboard.

What it does:
  - Serves as the Streamlit multi-page app root; all sidebar navigation pages
    are auto-discovered from the pages/ subdirectory.
  - Enforces authentication on load: redirects unauthenticated visitors to the
    login form and hides the sidebar nav until they log in.
  - Displays a welcome screen with navigation hints for the six management
    sections (User, Group, Budget, Usage, Model, Audit).
  - Shows a live "Quick Stats" panel: total user count, team count, and
    month-to-date spend pulled directly from the LiteLLM proxy API.
  - Explains the manual-only budget reset policy so admins understand why
    users can be blocked and what action is required to unblock them.

Depends on:
  auth.py                  — check_password() / logout_button()
  utils/litellm_client.py  — LiteLLMClient for the Quick Stats live query
"""
import streamlit as st
# ===== ADD THESE LINES AT THE VERY TOP =====
from auth import check_password, logout_button
# Hide sidebar pages if not authenticated
st.set_page_config(page_title="Claude code Admin", page_icon="🔑", layout="wide")
if not st.session_state.get("authenticated", False):
    st.markdown(
        """
        <style>
        [data-testid="stSidebarNav"] {display: none;}
        </style>
        """,
        unsafe_allow_html=True,
    )


# Block access if not authenticated
if not check_password():
    st.stop()

# Show logout button in sidebar
logout_button()


st.title("🏠 Claude code Admin Dashboard")
st.subheader("Claude Code via Bedrock — User & Budget Management")

st.divider()

st.write("### Welcome!")
st.write("Use the sidebar to navigate between pages:")

col1, col2 = st.columns(2)

with col1:
    st.write("#### 👥 Management")
    st.write("- **User Management** — Add, view, delete users and generate API keys")
    st.write("- **Group Management** — Create teams, assign users, import from Identity Center")
    st.write("- **Model Management** — View and add Bedrock models")

with col2:
    st.write("#### 💰 Monitoring & Controls")
    st.write("- **Budget Controls** — Set per-user and per-team budget limits")
    st.write("- **Usage Dashboard** — Real-time spend tracking and analytics")
    st.write("- **Spend Audit History** — Track all spend resets and lifetime usage")

st.divider()

st.write("### ⚙️ How Budget Enforcement Works")
st.info("""
**No auto-reset.** When a user hits their budget limit:
1. 🚫 LiteLLM blocks further API requests for that user
2. ⚠️ The Budget Controls page shows alerts for users at/over budget
3. 🔑 **Only an admin** can manually reset the spend counter
4. 📜 Every reset is recorded in the Spend Audit History with full trail

This ensures controlled usage — users cannot self-reset or exceed their budget.
""")

st.write("### 📊 Quick Stats")
try:
    from utils.litellm_client import LiteLLMClient
    client = LiteLLMClient()
    users = client.list_users()
    teams = client.list_teams()

    mcol1, mcol2, mcol3 = st.columns(3)
    with mcol1:
        st.metric("Total Users", len(users))
    with mcol2:
        st.metric("Total Teams", len(teams))
    with mcol3:
        total_spend = sum(u.get("spend", 0) for u in users)
        st.metric("Total Spend (MTD)", f"${total_spend:.2f}")
except Exception:
    st.warning("Unable to connect to LiteLLM. Make sure the proxy is running.")
