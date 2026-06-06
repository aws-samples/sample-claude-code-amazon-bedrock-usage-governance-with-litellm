"""
litellm-admin-dashboard/pages/2_Group_Management.py

Streamlit page: Group / Team Management.

What it does:
  - Tab 1 — View / Manage Teams: lists every LiteLLM team with spend, budget,
    member roster, and allowed models. Per-team expanders let admins:
      • Add or remove individual members (synced to IAM Identity Center group).
      • Reset team spend to $0 (logged to the audit table first).
      • Delete the team from both LiteLLM and Identity Center.
  - Tab 2 — Create Team: form to create a new team in LiteLLM and a matching
    group in IAM Identity Center in one step, with optional member pre-selection
    from existing users.
  - Tab 3 — Import from Identity Center: fetches all IC groups, lets the admin
    select which to import, then creates LiteLLM teams with matching members
    (creating new LiteLLM users for IC members that don't yet exist).
  - Tab 4 — Move User Between Teams: transfers a user from one team to another,
    updating both LiteLLM membership and IAM Identity Center group membership
    atomically.

Budget policy: NO budget_duration — team spend never auto-resets.
When a team hits its budget, all members are blocked until an admin resets via
Tab 1 or the Budget Controls page.

Depends on:
  utils/litellm_client.py   — team/user CRUD, member operations, spend reset.
  utils/identity_center.py  — group read/write/move (disabled if unconfigured).
  utils/spend_tracker.py    — audit log for team spend resets.
  utils/config_loader.py    — default budgets, models, limits from config.yaml.
"""
import streamlit as st
from utils.litellm_client import LiteLLMClient
from utils.identity_center import IdentityCenterClient
from utils.spend_tracker import SpendResetTracker
from utils.config_loader import get_allowed_models, get_default_team_models, get_defaults
import os

st.set_page_config(page_title="Group Management", page_icon="🏢", layout="wide")
st.title("🏢 Group / Team Management")

client = LiteLLMClient()
spend_tracker = SpendResetTracker(os.environ.get("DATABASE_URL"))

# Load configuration
AVAILABLE_MODELS = get_allowed_models()
DEFAULT_TEAM_MODELS = get_default_team_models()
DEFAULTS = get_defaults()

# Initialize Identity Center client
try:
    ic_client = IdentityCenterClient()
    ic_available = True
except Exception:
    ic_available = False

tab1, tab2, tab3, tab4 = st.tabs([
    "📋 View/Manage Teams",
    "➕ Create Team",
    "🔄 Import from Identity Center",
    "🔀 Move User Between Teams"
])

# ========== TAB 1: View/Manage Teams ==========
with tab1:
    st.subheader("Existing Teams")
    try:
        teams = client.list_teams()
        # all_users = client.list_users()
        all_users = [u for u in client.list_users() if u.get("user_id") != "default_user_id"]
        if not teams:
            st.info("No teams found. Create a team or import from Identity Center.")
        else:
            for team in teams:
                team_id = team.get("team_id", "N/A")
                team_alias = team.get("team_alias", "Unnamed Team")
                spend = team.get("spend", 0)
                max_budget = team.get("max_budget", None)
                models = team.get("models", [])
                members = team.get("members_with_roles", [])

                budget_display = f"${max_budget}" if max_budget else "Unlimited"
                with st.expander(f"🏢 {team_alias} | Spend: ${spend:.2f} / {budget_display} | Members: {len(members)}"):
                    col1, col2 = st.columns(2)

                    with col1:
                        st.write(f"**Team ID:** {team_id}")
                        st.write(f"**Alias:** {team_alias}")
                        st.write(f"**Max Budget:** {budget_display}")
                        st.write(f"**TPM Limit:** {team.get('tpm_limit', 'Unlimited')}")
                        st.write(f"**RPM Limit:** {team.get('rpm_limit', 'Unlimited')}")

                    with col2:
                        st.write(f"**Allowed Models:** {', '.join(models) if models else 'All'}")
                        st.write(f"**Current Spend:** ${spend:.4f}")
                        st.write("**Reset Policy:** Manual only (no auto-reset)")

                    # Members section with remove option
                    if members:
                        st.write("**Members:**")
                        for member in members:
                            member_id = member.get("user_id", "Unknown")
                            member_role = member.get("role", "member")
                            mem_col1, mem_col2 = st.columns([3, 1])
                            with mem_col1:
                                st.write(f"  👤 {member_id} ({member_role})")
                            with mem_col2:
                                if st.button("❌ Remove", key=f"remove_{team_id}_{member_id}"):
                                    st.session_state[f"confirm_remove_{team_id}_{member_id}"] = True

                            # Remove member confirmation
                            if st.session_state.get(f"confirm_remove_{team_id}_{member_id}", False):
                                st.warning(f"Remove **{member_id}** from team **{team_alias}**?")
                                rc1, rc2 = st.columns(2)
                                with rc1:
                                    if st.button("✅ Yes", key=f"yes_remove_{team_id}_{member_id}"):
                                        try:
                                            # 1. Remove from LiteLLM team
                                            client.remove_team_member(team_id=team_id, user_id=member_id)

                                            # 2. Remove from IC group
                                            if ic_available:
                                                try:
                                                    ic_group = ic_client.get_group_by_name(team_alias)
                                                    ic_user = ic_client.get_user_by_username(member_id)
                                                    if ic_group and ic_user:
                                                        membership_id = ic_client.get_membership_id(
                                                            user_id=ic_user["user_id"],
                                                            group_id=ic_group["group_id"]
                                                        )
                                                        if membership_id:
                                                            ic_client.remove_user_from_group(membership_id)
                                                except Exception as ic_err:
                                                    st.warning(f"⚠️ Removed from LiteLLM but IC sync failed: {ic_err}")

                                            st.success(f"✅ {member_id} removed from {team_alias}")
                                            st.session_state[f"confirm_remove_{team_id}_{member_id}"] = False
                                            st.rerun()
                                        except Exception as e:
                                            st.error(f"Failed: {e}")
                                with rc2:
                                    if st.button("❌ No", key=f"no_remove_{team_id}_{member_id}"):
                                        st.session_state[f"confirm_remove_{team_id}_{member_id}"] = False
                                        st.rerun()
                    else:
                        st.write("**Members:** None")

                    st.divider()

                    # Add user to this team
                    st.write("**➕ Add User to Team:**")
                    # Get users not already in this team
                    current_member_ids = [m.get("user_id", "") for m in members]
                    available_users = [u.get("user_id", "") for u in all_users if u.get("user_id", "") not in current_member_ids]

                    if available_users:
                        add_col1, add_col2 = st.columns([3, 1])
                        with add_col1:
                            user_to_add = st.selectbox(
                                "Select user",
                                options=available_users,
                                key=f"add_user_to_{team_id}"
                            )
                        with add_col2:
                            if st.button("➕ Add", key=f"btn_add_user_{team_id}"):
                                try:
                                    # 1. Add to LiteLLM team
                                    client.add_team_member(team_id=team_id, user_id=user_to_add, role="user")

                                    # 2. Add to IC group
                                    if ic_available:
                                        try:
                                            ic_group = ic_client.get_group_by_name(team_alias)
                                            ic_user = ic_client.get_user_by_username(user_to_add)
                                            if ic_group and ic_user:
                                                ic_client.add_user_to_group(
                                                    user_id=ic_user["user_id"],
                                                    group_id=ic_group["group_id"]
                                                )
                                        except Exception as ic_err:
                                            st.warning(f"⚠️ Added to LiteLLM but IC sync failed: {ic_err}")

                                    st.success(f"✅ {user_to_add} added to {team_alias}")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Failed to add user: {e}")
                    else:
                        st.caption("All users are already in this team.")

                    st.divider()

                    # Status indicator
                    if max_budget and max_budget > 0:
                        pct = (spend / max_budget) * 100
                        if pct >= 100:
                            st.error(f"🚫 Team is OVER BUDGET ({pct:.0f}%). All team members are blocked. Admin must reset spend.")
                        elif pct >= 80:
                            st.warning(f"⚠️ Team at {pct:.0f}% of budget.")
                        else:
                            st.success(f"✅ Team at {pct:.0f}% of budget.")
                    else:
                        pct = 0

                    # Action buttons - Reset and Delete
                    btn_col1, btn_col2 = st.columns(2)

                    with btn_col1:
                        if st.button(f"🔄 Reset Team Spend", key=f"reset_team_{team_id}"):
                            try:
                                current_spend = team.get("spend", 0)
                                if current_spend > 0:
                                    spend_tracker.record_team_reset(
                                        team_id=team_id,
                                        spend_before_reset=current_spend,
                                        reset_by="admin",
                                        notes=f"Manual reset for team '{team_alias}'"
                                    )
                                    client.reset_team_budget(team_id)
                                    st.success(
                                        f"✅ Team spend reset to $0 for '{team_alias}'\n\n"
                                        f"📊 Previous spend: ${current_spend:.4f}\n\n"
                                        f"📜 Recorded in audit history."
                                    )
                                else:
                                    st.info("Team spend is already $0.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Failed to reset team spend: {e}")

                    with btn_col2:
                        if st.button(f"🗑️ Delete Team", key=f"delete_team_{team_id}", type="secondary"):
                            st.session_state[f"confirm_delete_{team_id}"] = True

                    # Delete confirmation
                    if st.session_state.get(f"confirm_delete_{team_id}", False):
                        st.warning(
                            f"⚠️ Are you sure you want to delete team **'{team_alias}'**?\n\n"
                            f"This will:\n"
                            f"- Remove the team from LiteLLM\n"
                            f"- Delete the corresponding group from IAM Identity Center\n"
                            f"- Members will NOT be deleted but will lose team/group association"
                        )
                        confirm_col1, confirm_col2 = st.columns(2)
                        with confirm_col1:
                            if st.button(f"✅ Yes, Delete", key=f"confirm_yes_{team_id}", type="primary"):
                                try:
                                    # 1. Delete from LiteLLM
                                    client.delete_team(team_id)

                                    # 2. Delete from IAM Identity Center
                                    if ic_available:
                                        try:
                                            ic_group = ic_client.get_group_by_name(team_alias)
                                            if ic_group:
                                                ic_client.delete_group(ic_group["group_id"])
                                        except Exception as ic_err:
                                            st.warning(f"⚠️ Team deleted from LiteLLM but IC cleanup failed: {ic_err}")

                                    st.success(f"✅ Team '{team_alias}' deleted from LiteLLM and Identity Center.")
                                    st.session_state[f"confirm_delete_{team_id}"] = False
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Failed to delete team: {e}")
                        with confirm_col2:
                            if st.button(f"❌ Cancel", key=f"confirm_no_{team_id}"):
                                st.session_state[f"confirm_delete_{team_id}"] = False
                                st.rerun()

    except Exception as e:
        st.error(f"Error fetching teams: {e}")

# ========== TAB 2: Create New Team (with Members) ==========
with tab2:
    st.subheader("Create New Team")
    st.info(
        "💡 Creates team in BOTH LiteLLM and IAM Identity Center with selected members. "
        "Teams have no auto-reset. When team budget is hit, all team members are blocked until admin resets."
    )

    with st.form("create_team_form"):
        team_name = st.text_input("Team Name", placeholder="Engineering-Team")
        team_description = st.text_input("Description (optional)", placeholder="Engineering team for backend services")
        team_budget = st.number_input(
            "Monthly Budget (USD)",
            min_value=0.0,
            value=DEFAULTS["team_budget"],
            step=50.0,
            help="Team is blocked when total team spend hits this amount."
        )
        team_tpm = st.number_input(
            "TPM Limit (tokens per minute)",
            min_value=0,
            value=DEFAULTS["team_tpm"],
            step=50000
        )
        team_rpm = st.number_input(
            "RPM Limit (requests per minute)",
            min_value=0,
            value=DEFAULTS["team_rpm"],
            step=10
        )

        # Models from config
        team_models = st.multiselect(
            "Allowed Models",
            AVAILABLE_MODELS,
            default=DEFAULT_TEAM_MODELS
        )

        # Select users to add to this team
        st.divider()
        st.write("**👥 Add Members to Team (optional):**")
        st.caption("Select existing users to add as members of this team during creation.")
        try:
            # existing_users = client.list_users()
            existing_users = [u for u in client.list_users() if u.get("user_id") != "default_user_id"]
            user_options = [u.get("user_id", "") for u in existing_users]
        except Exception:
            user_options = []

        selected_members = st.multiselect(
            "Select Users to Add",
            options=user_options,
            default=[],
            key="create_team_members"
        )

        submitted = st.form_submit_button("Create Team", type="primary")
        if submitted:
            if not team_name:
                st.error("Team name is required.")
            else:
                try:
                    # 1. Create team in LiteLLM
                    result = client.create_team(
                        team_alias=team_name,
                        max_budget=team_budget,
                        tpm_limit=team_tpm,
                        rpm_limit=team_rpm,
                        allowed_models=team_models if team_models else None
                    )
                    team_id = result.get('team_id', 'N/A')

                    # 2. Create group in IAM Identity Center
                    ic_group_result = None
                    if ic_available:
                        try:
                            ic_group_result = ic_client.create_group(
                                group_name=team_name,
                                description=team_description or f"Team: {team_name}"
                            )
                        except Exception as ic_err:
                            st.warning(f"⚠️ Team created in LiteLLM but IC group creation failed: {ic_err}")

                    # 3. Add selected members to team
                    members_added = 0
                    members_failed = 0
                    for member_id in selected_members:
                        try:
                            # Add to LiteLLM team
                            client.add_team_member(team_id=team_id, user_id=member_id, role="user")

                            # Add to IC group
                            if ic_available and ic_group_result:
                                try:
                                    ic_user = ic_client.get_user_by_username(member_id)
                                    if ic_user:
                                        ic_client.add_user_to_group(
                                            user_id=ic_user["user_id"],
                                            group_id=ic_group_result["group_id"]
                                        )
                                except Exception:
                                    pass  # Non-critical

                            members_added += 1
                        except Exception:
                            members_failed += 1

                    st.success(f"✅ Team '{team_name}' created!")
                    st.write(f"**LiteLLM Team ID:** {team_id}")
                    if ic_group_result:
                        st.write(f"**Identity Center Group ID:** {ic_group_result['group_id']}")
                    if selected_members:
                        st.write(f"**Members Added:** {members_added}")
                        if members_failed > 0:
                            st.warning(f"⚠️ {members_failed} members failed to add.")

                except Exception as e:
                    st.error(f"Failed to create team: {e}")

# ========== TAB 3: Import from Identity Center ==========
with tab3:
    st.subheader("Import Identity Center Groups as Teams")
    st.info("Fetches groups from IAM Identity Center → Creates LiteLLM teams with members mapped. No auto-reset.")

    if not ic_available:
        st.error("❌ IAM Identity Center is not configured. Set IDENTITY_STORE_ID environment variable.")
    else:
        col1, col2 = st.columns(2)
        with col1:
            import_budget = st.number_input(
                "Default Team Budget (USD)", min_value=0.0,
                value=DEFAULTS["team_budget"], step=50.0, key="import_team_budget"
            )
            import_user_budget = st.number_input(
                "Default Per-User Budget (USD)", min_value=0.0,
                value=DEFAULTS["user_budget"], step=10.0, key="import_user_budget"
            )
        with col2:
            import_tpm = st.number_input(
                "Default Team TPM", min_value=0,
                value=DEFAULTS["team_tpm"], step=50000, key="import_tpm"
            )
            import_user_tpm = st.number_input(
                "Default Per-User TPM", min_value=0,
                value=DEFAULTS["user_tpm"], step=10000, key="import_user_tpm"
            )

        if st.button("🔄 Fetch Groups from Identity Center"):
            try:
                ic_groups = ic_client.list_groups()
                if not ic_groups:
                    st.warning("No groups found.")
                else:
                    st.success(f"Found {len(ic_groups)} groups")
                    st.session_state["ic_groups"] = ic_groups
            except Exception as e:
                st.error(f"Failed: {e}")

        if "ic_groups" in st.session_state and st.session_state["ic_groups"]:
            ic_groups = st.session_state["ic_groups"]
            selected_groups = st.multiselect(
                "Select groups to import",
                options=[g["display_name"] for g in ic_groups],
                default=[g["display_name"] for g in ic_groups]
            )

            if st.button("📥 Import Selected Groups", type="primary"):
                imported_teams = 0
                imported_users = 0
                errors = 0

                progress = st.progress(0)
                for idx, group in enumerate(ic_groups):
                    if group["display_name"] in selected_groups:
                        try:
                            # Create team in LiteLLM
                            team_result = client.create_team(
                                team_alias=group["display_name"],
                                max_budget=import_budget,
                                tpm_limit=import_tpm
                            )
                            team_id = team_result.get("team_id")
                            imported_teams += 1

                            # Fetch and import members
                            members = ic_client.get_group_members(group["group_id"])
                            for member in members:
                                try:
                                    # Create user in LiteLLM
                                    client.create_user(
                                        user_id=member["username"],
                                        user_email=member.get("email", ""),
                                        max_budget=import_user_budget,
                                        tpm_limit=import_user_tpm,
                                        team_id=team_id
                                    )
                                    # Add as team member (shows in members_with_roles)
                                    client.add_team_member(
                                        team_id=team_id,
                                        user_id=member["username"],
                                        role="user"
                                    )
                                    imported_users += 1
                                except Exception:
                                    # User might already exist, try just adding to team
                                    try:
                                        client.add_team_member(
                                            team_id=team_id,
                                            user_id=member["username"],
                                            role="user"
                                        )
                                        imported_users += 1
                                    except Exception:
                                        errors += 1
                        except Exception:
                            errors += 1
                    progress.progress((idx + 1) / len(ic_groups))

                st.success(f"✅ Imported {imported_teams} teams, {imported_users} users with team mapping!")
                if errors > 0:
                    st.warning(f"⚠️ {errors} items failed (may already exist)")

# ========== TAB 4: Move User Between Teams ==========
with tab4:
    st.subheader("🔀 Move User Between Teams")
    st.info(
        "Move a user from one team to another. "
        "This updates BOTH LiteLLM and IAM Identity Center simultaneously."
    )

    if not ic_available:
        st.error("❌ IAM Identity Center is not configured. Set IDENTITY_STORE_ID environment variable.")
    else:
        try:
            teams = client.list_teams()
            # users = client.list_users()
            users = [u for u in client.list_users() if u.get("user_id") != "default_user_id"]
            if not teams:
                st.warning("No teams found. Create teams first.")
            elif not users:
                st.warning("No users found.")
            else:
                # Build team lookup
                team_lookup = {t.get("team_id"): t.get("team_alias", t.get("team_id")) for t in teams}
                team_name_to_id = {t.get("team_alias", ""): t.get("team_id", "") for t in teams}

                # Select user
                user_ids = [u.get("user_id", "") for u in users]
                selected_user = st.selectbox("Select User to Move", user_ids, key="move_user_select")

                if selected_user:
                    # Show current team membership
                    current_teams = []
                    for team in teams:
                        members = team.get("members_with_roles", [])
                        for m in members:
                            if m.get("user_id") == selected_user:
                                current_teams.append(team.get("team_alias", team.get("team_id")))

                    if current_teams:
                        st.write(f"**Current Team(s):** {', '.join(current_teams)}")
                    else:
                        st.write("**Current Team(s):** None")

                    col1, col2 = st.columns(2)
                    with col1:
                        from_team = st.selectbox(
                            "From Team",
                            options=current_teams if current_teams else list(team_name_to_id.keys()),
                            key="from_team_select"
                        )
                    with col2:
                        available_to_teams = [t for t in team_name_to_id.keys() if t != from_team]
                        to_team = st.selectbox(
                            "To Team",
                            options=available_to_teams,
                            key="to_team_select"
                        )

                    if st.button("🔀 Move User", type="primary"):
                        if from_team and to_team and from_team != to_team:
                            try:
                                from_team_id = team_name_to_id.get(from_team, "")
                                to_team_id = team_name_to_id.get(to_team, "")

                                # 1. Remove from old team in LiteLLM
                                try:
                                    client.remove_team_member(team_id=from_team_id, user_id=selected_user)
                                except Exception:
                                    pass

                                # 2. Add to new team in LiteLLM
                                client.add_team_member(team_id=to_team_id, user_id=selected_user, role="user")

                                # 3. Move in IAM Identity Center
                                ic_success = False
                                if ic_available:
                                    try:
                                        ic_user = ic_client.get_user_by_username(selected_user)
                                        if ic_user:
                                            from_ic_group = ic_client.get_group_by_name(from_team)
                                            to_ic_group = ic_client.get_group_by_name(to_team)

                                            if from_ic_group and to_ic_group:
                                                ic_client.move_user_between_groups(
                                                    user_id=ic_user["user_id"],
                                                    from_group_id=from_ic_group["group_id"],
                                                    to_group_id=to_ic_group["group_id"]
                                                )
                                                ic_success = True
                                            elif to_ic_group:
                                                ic_client.add_user_to_group(
                                                    user_id=ic_user["user_id"],
                                                    group_id=to_ic_group["group_id"]
                                                )
                                                ic_success = True
                                    except Exception as ic_err:
                                        st.warning(f"⚠️ Moved in LiteLLM but IC sync failed: {ic_err}")

                                if ic_success:
                                    st.success(
                                        f"✅ User '{selected_user}' moved from '{from_team}' to '{to_team}'\n\n"
                                        f"Updated in both LiteLLM and IAM Identity Center."
                                    )
                                else:
                                    st.success(
                                        f"✅ User '{selected_user}' moved from '{from_team}' to '{to_team}' in LiteLLM."
                                    )
                                st.rerun()

                            except Exception as e:
                                st.error(f"Failed to move user: {e}")
                        else:
                            st.error("Source and destination teams must be different.")

        except Exception as e:
            st.error(f"Error: {e}")
