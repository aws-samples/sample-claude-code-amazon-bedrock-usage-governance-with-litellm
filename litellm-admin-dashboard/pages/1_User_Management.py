"""
litellm-admin-dashboard/pages/1_User_Management.py

Streamlit page: User Management.

What it does:
  - Tab 1 — View / Manage Users: lists every LiteLLM user (excluding the
    internal default_user_id) with their spend, budget, models, and API keys.
    Each row has buttons to delete the user (with a confirmation step) and to
    reset their spend counter to $0. Every reset is logged to the audit table
    via SpendResetTracker before the LiteLLM call is made.
  - Tab 2 — Add User: form to create a new LiteLLM user with a generated API
    key. Simultaneously creates the user in AWS IAM Identity Center if the
    integration is available. Budget, TPM/RPM limits, and allowed models are
    pre-filled from config.yaml defaults.
  - Tab 3 — Sync from Identity Center: fetches all users from IAM Identity
    Center and batch-imports any that don't already exist in LiteLLM, applying
    default budgets and limits from config.yaml.

Depends on:
  utils/litellm_client.py   — user CRUD, spend reset.
  utils/identity_center.py  — IC user read/create (gracefully disabled if
                               IDENTITY_STORE_ID is not set).
  utils/spend_tracker.py    — audit log for spend resets.
  utils/config_loader.py    — default budgets, models, limits from config.yaml.
"""
import streamlit as st
from utils.litellm_client import LiteLLMClient
from utils.identity_center import IdentityCenterClient
from utils.spend_tracker import SpendResetTracker
from utils.config_loader import get_allowed_models, get_default_user_models, get_defaults
import os, time

st.set_page_config(page_title="User Management", page_icon="👥", layout="wide")
st.title("👥 User Management")

client = LiteLLMClient()
spend_tracker = SpendResetTracker(os.environ.get("DATABASE_URL"))

# Initialize Identity Center client
try:
    ic_client = IdentityCenterClient()
    ic_available = True
except Exception:
    ic_available = False

# Load configuration
AVAILABLE_MODELS = get_allowed_models()
DEFAULT_USER_MODELS = get_default_user_models()
DEFAULTS = get_defaults()

tab1, tab2, tab3 = st.tabs(["📋 View/Manage Users", "➕ Add User", "🔄 Sync from Identity Center"])

# ========== TAB 1: View/Manage Users ==========
with tab1:
    st.subheader("Existing Users")
    try:
        # users = client.list_users()
        users = [u for u in client.list_users() if u.get("user_id") != "default_user_id"]
        if not users:
            st.info("No users found. Add users manually or sync from Identity Center.")
        else:
            for user in users:
                user_id = user.get("user_id", "N/A")
                email = user.get("user_email", "N/A")
                spend = user.get("spend", 0)
                max_budget = user.get("max_budget", None)
                models = user.get("models", [])

                # Status indicator
                if max_budget and max_budget > 0:
                    pct = (spend / max_budget) * 100
                    status = "🔴 BLOCKED" if pct >= 100 else ("🟡" if pct >= 80 else "🟢")
                else:
                    status = "🟢"
                    pct = 0

                with st.expander(f"{status} {user_id} — {email} | ${spend:.2f} / ${max_budget if max_budget else '∞'}"):
                    col1, col2, col3 = st.columns(3)

                    with col1:
                        st.write(f"**User ID:** {user_id}")
                        st.write(f"**Email:** {email}")
                        st.write(f"**Team:** {user.get('team_id', 'None')}")

                    with col2:
                        st.write(f"**Spend:** ${spend:.4f}")
                        st.write(f"**Max Budget:** ${max_budget}" if max_budget else "**Max Budget:** Unlimited")
                        st.write(f"**TPM Limit:** {user.get('tpm_limit', 'Unlimited')}")
                        st.write(f"**RPM Limit:** {user.get('rpm_limit', 'Unlimited')}")

                    with col3:
                        st.write(f"**Allowed Models:** {', '.join(models) if models else 'All'}")
                        # Show lifetime spend
                        summary = spend_tracker.get_user_summary(user_id)
                        if summary["total_resets"] > 0:
                            lifetime = summary["lifetime_spend"] + spend
                            st.write(f"**Lifetime Spend:** ${lifetime:.4f}")
                            st.write(f"**Total Resets:** {summary['total_resets']}")

                    if pct >= 100:
                        st.error(f"🚫 User is OVER BUDGET ({pct:.0f}%). API requests are blocked. Admin must reset spend.")

                    st.divider()
                    action_col1, action_col2, action_col3 = st.columns(3)

                    with action_col1:
                        if st.button(f"🔑 Generate Key", key=f"genkey_{user_id}"):
                            try:
                                result = client.generate_key(
                                    user_id=user_id,
                                    key_alias=f"key-{user_id}-{int(time.time())}"
                                )
                                st.success(f"Key generated!")
                                st.code(result.get("key", ""), language=None)
                                st.warning("⚠️ Copy this key now! It won't be shown again.")
                            except Exception as e:
                                st.error(f"Failed to generate key: {e}")

                    with action_col2:
                        if st.button(f"🔄 Reset Spend", key=f"reset_{user_id}"):
                            try:
                                current_spend = user.get("spend", 0)
                                if current_spend > 0:
                                    # Record in audit FIRST
                                    audit_result = spend_tracker.record_reset(
                                        user_id=user_id,
                                        spend_before_reset=current_spend,
                                        reset_by="admin",
                                        notes="Manual reset from User Management"
                                    )
                                    # Then reset
                                    client.reset_user_budget(user_id)
                                    st.success(
                                        f"✅ Spend reset to $0 for {user_id}\n\n"
                                        f"📊 Reset #{audit_result['total_resets']} | "
                                        f"Recorded: ${current_spend:.4f} | "
                                        f"Lifetime: ${audit_result['cumulative_lifetime_spend']:.4f}"
                                    )
                                else:
                                    st.info("Spend is already $0.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Failed to reset spend: {e}")

                    with action_col3:
                        if st.button(f"🗑️ Delete User", key=f"delete_{user_id}", type="secondary"):
                            st.session_state[f"confirm_delete_user_{user_id}"] = True

                    # Delete confirmation with IC sync
                    if st.session_state.get(f"confirm_delete_user_{user_id}", False):
                        st.warning(
                            f"⚠️ Are you sure you want to delete user **'{user_id}'**?\n\n"
                            f"This will:\n"
                            f"- Remove the user from LiteLLM (keys will be invalidated)\n"
                            f"- Remove the user from IAM Identity Center\n"
                            f"- Remove all group/team memberships"
                        )
                        confirm_col1, confirm_col2 = st.columns(2)
                        with confirm_col1:
                            if st.button(f"✅ Yes, Delete", key=f"confirm_del_yes_{user_id}", type="primary"):
                                try:
                                    # 1. Delete from LiteLLM
                                    client.delete_user([user_id])

                                    # 2. Delete from IAM Identity Center
                                    if ic_available:
                                        try:
                                            ic_user = ic_client.get_user_by_username(user_id)
                                            if ic_user:
                                                ic_client.delete_user(ic_user["user_id"])
                                        except Exception as ic_err:
                                            st.warning(f"⚠️ Deleted from LiteLLM but IC cleanup failed: {ic_err}")

                                    st.success(f"✅ User '{user_id}' deleted from LiteLLM and Identity Center.")
                                    st.session_state[f"confirm_delete_user_{user_id}"] = False
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Failed to delete user: {e}")
                        with confirm_col2:
                            if st.button(f"❌ Cancel", key=f"confirm_del_no_{user_id}"):
                                st.session_state[f"confirm_delete_user_{user_id}"] = False
                                st.rerun()

    except Exception as e:
        st.error(f"Error fetching users: {e}")

# ========== TAB 2: Add User Manually ==========
with tab2:
    st.subheader("Add New User")
    st.info(
        "💡 Creates user in BOTH LiteLLM and IAM Identity Center. "
        "New users have NO auto-reset. When their budget is hit, they are blocked until an admin manually resets their spend."
    )

    with st.form("add_user_form"):
        new_user_id = st.text_input("User ID (e.g., john.doe)", placeholder="john.doe")
        new_user_email = st.text_input("Email", placeholder="john.doe@company.com")
        new_first_name = st.text_input("First Name", placeholder="John")
        new_last_name = st.text_input("Last Name", placeholder="Doe")
        new_max_budget = st.number_input(
            "Monthly Budget (USD)",
            min_value=0.0,
            value=DEFAULTS["user_budget"],
            step=10.0,
            help="User is blocked when spend reaches this amount. Admin must manually reset."
        )
        new_tpm_limit = st.number_input(
            "TPM Limit (tokens per minute)",
            min_value=0,
            value=DEFAULTS["user_tpm"],
            step=10000
        )
        new_rpm_limit = st.number_input(
            "RPM Limit (requests per minute)",
            min_value=0,
            value=DEFAULTS["user_rpm"],
            step=5
        )

        # Get available teams
        try:
            teams = client.list_teams()
            team_options = ["None"] + [t.get("team_alias", t.get("team_id", "")) for t in teams]
            team_ids = [None] + [t.get("team_id", "") for t in teams]
        except Exception:
            team_options = ["None"]
            team_ids = [None]

        selected_team = st.selectbox("Assign to Team", team_options)
        team_id = team_ids[team_options.index(selected_team)] if selected_team != "None" else None

        # Models from config
        selected_models = st.multiselect(
            "Allowed Models",
            AVAILABLE_MODELS,
            default=DEFAULT_USER_MODELS
        )

        submitted = st.form_submit_button("Create User", type="primary")
        if submitted:
            if not new_user_id or not new_user_email:
                st.error("User ID and Email are required.")
            elif not new_first_name or not new_last_name:
                st.error("First Name and Last Name are required for Identity Center sync.")
            else:
                try:
                    # 1. Create in LiteLLM
                    result = client.create_user(
                        user_id=new_user_id,
                        user_email=new_user_email,
                        max_budget=new_max_budget,
                        tpm_limit=new_tpm_limit,
                        rpm_limit=new_rpm_limit,
                        allowed_models=selected_models if selected_models else None,
                        team_id=team_id
                    )

                    # If team is selected, also add as team member
                    if team_id:
                        try:
                            client.add_team_member(team_id=team_id, user_id=new_user_id, role="user")
                        except Exception:
                            pass  # Might fail if already added via create_user

                    # 2. Create in IAM Identity Center
                    ic_user_result = None
                    if ic_available:
                        try:
                            ic_user_result = ic_client.create_user(
                                username=new_user_id,
                                first_name=new_first_name,
                                last_name=new_last_name,
                                email=new_user_email,
                                display_name=f"{new_first_name} {new_last_name}"
                            )
                        except Exception as ic_err:
                            st.warning(f"⚠️ User created in LiteLLM but IC creation failed: {ic_err}")

                    # 3. If team selected, add to IC group too
                    if ic_available and ic_user_result and team_id:
                        try:
                            # Find the IC group matching the selected team
                            selected_team_alias = selected_team
                            ic_group = ic_client.get_group_by_name(selected_team_alias)
                            if ic_group:
                                ic_client.add_user_to_group(
                                    user_id=ic_user_result["user_id"],
                                    group_id=ic_group["group_id"]
                                )
                        except Exception:
                            pass  # Non-critical, group might not exist in IC

                    st.success(f"✅ User '{new_user_id}' created successfully!")
                    if ic_user_result:
                        st.write(f"**Identity Center User ID:** {ic_user_result['user_id']}")

                    # Auto-generate key
                    key_result = client.generate_key(
                        user_id=new_user_id,
                        key_alias=f"key-{new_user_id}-{int(time.time())}"
                    )
                    st.info("🔑 API Key generated:")
                    st.code(key_result.get("key", ""), language=None)
                    st.warning("⚠️ Copy and share this key securely. It won't be shown again.")
                except Exception as e:
                    st.error(f"Failed to create user: {e}")

# ========== TAB 3: Sync from Identity Center ==========
with tab3:
    st.subheader("Import Users from IAM Identity Center")
    st.info("Fetches users from Identity Center → Creates them in LiteLLM with budget limits. No auto-reset.")

    if not ic_available:
        st.error("❌ IAM Identity Center is not configured. Set IDENTITY_STORE_ID environment variable.")
    else:
        col1, col2 = st.columns(2)
        with col1:
            default_budget = st.number_input(
                "Default Budget for Imported Users (USD)",
                min_value=0.0,
                value=DEFAULTS["user_budget"],
                step=10.0,
                key="sync_budget"
            )
        with col2:
            default_tpm = st.number_input(
                "Default TPM Limit",
                min_value=0,
                value=DEFAULTS["user_tpm"],
                step=10000,
                key="sync_tpm"
            )

        if st.button("🔄 Fetch Users from Identity Center"):
            try:
                ic_users = ic_client.list_users()

                if not ic_users:
                    st.warning("No users found in Identity Center.")
                else:
                    st.success(f"Found {len(ic_users)} users in Identity Center")
                    st.session_state["ic_users"] = ic_users
            except Exception as e:
                st.error(f"Failed to fetch from Identity Center: {e}")

        if "ic_users" in st.session_state and st.session_state["ic_users"]:
            ic_users = st.session_state["ic_users"]

            import pandas as pd
            df = pd.DataFrame(ic_users)
            st.dataframe(df, use_container_width=True)

            selected_users = st.multiselect(
                "Select users to import",
                options=[u["username"] for u in ic_users],
                default=[u["username"] for u in ic_users]
            )

            if st.button("📥 Import Selected Users", type="primary"):
                imported = 0
                errors = 0
                for user in ic_users:
                    if user["username"] in selected_users:
                        try:
                            client.create_user(
                                user_id=user["username"],
                                user_email=user.get("email", f"{user['username']}@company.com"),
                                max_budget=default_budget,
                                tpm_limit=default_tpm
                            )
                            imported += 1
                        except Exception:
                            errors += 1

                st.success(f"✅ Imported {imported} users!")
                if errors > 0:
                    st.warning(f"⚠️ {errors} users failed (may already exist)")
