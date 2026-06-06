"""
litellm-admin-dashboard/pages/3_Budget_Controls.py

Streamlit page: Budget Controls.

What it does:
  - Tab 1 — Per-User Limits: shows a budget alert banner for any user at or
    above 80% of their limit (100% = blocked), then lets admins edit each
    user's USD budget cap, TPM limit, RPM limit, and allowed models in-line.
    Includes a one-click spend reset per user (logged to the audit table).
  - Tab 2 — Per-Team Limits: same controls applied at the team level — budget,
    TPM, RPM — with a spend reset button per team.
  - Tab 3 — Bulk Actions: lets admins apply a new budget or rate limit to all
    users or all teams at once, and bulk-reset all spend counters in a single
    operation.

Budget enforcement model:
  LiteLLM hard-blocks API requests the moment a user or team reaches their
  budget. There is no auto-reset (budget_duration is not set). Only an admin
  manually resetting via this page or the Group Management page can unblock
  a user. Every reset is recorded in the Spend Audit History.

Depends on:
  utils/litellm_client.py  — user/team update and spend reset.
  utils/spend_tracker.py   — audit log for every reset action.
  utils/config_loader.py   — default budgets and limits from config.yaml.
"""
import streamlit as st
import pandas as pd
from utils.litellm_client import LiteLLMClient
from utils.spend_tracker import SpendResetTracker
from utils.config_loader import get_allowed_models, get_defaults
import os

st.set_page_config(page_title="Budget Controls", page_icon="💰", layout="wide")
st.title("💰 Budget Controls")

client = LiteLLMClient()
spend_tracker = SpendResetTracker(os.environ.get("DATABASE_URL"))

# Load configuration
AVAILABLE_MODELS = get_allowed_models()
DEFAULTS = get_defaults()

tab1, tab2, tab3 = st.tabs(["👤 Per-User Limits", "🏢 Per-Team Limits", "⚡ Bulk Actions"])

# ========== TAB 1: Per-User Limits ==========
with tab1:
    st.subheader("Per-User Budget Limits")
    try:
        users = client.list_users()
        if not users:
            st.info("No users found.")
        else:
            # Budget alerts
            st.write("### ⚠️ Budget Alerts")
            st.caption("Users at or above 80% of budget. Users at 100% are BLOCKED from API access.")
            alerts = []
            for user in users:
                spend = user.get("spend", 0)
                max_budget = user.get("max_budget", None)
                if max_budget and max_budget > 0:
                    pct = (spend / max_budget) * 100
                    if pct >= 80:
                        alerts.append({
                            "user": user.get("user_id"),
                            "spend": spend,
                            "budget": max_budget,
                            "pct": pct
                        })

            if alerts:
                for alert in sorted(alerts, key=lambda x: x["pct"], reverse=True):
                    if alert["pct"] >= 100:
                        st.error(f"🔴 **{alert['user']}** — ${alert['spend']:.2f} / ${alert['budget']:.2f} ({alert['pct']:.1f}%) — **BLOCKED**")
                    else:
                        st.warning(f"🟡 **{alert['user']}** — ${alert['spend']:.2f} / ${alert['budget']:.2f} ({alert['pct']:.1f}%)")
            else:
                st.success("✅ No users near their budget limits.")

            st.divider()
            st.write("### Modify User Limits")

            user_ids = [u.get("user_id", "") for u in users]
            selected_user = st.selectbox("Select User", user_ids)

            if selected_user:
                user_data = next((u for u in users if u.get("user_id") == selected_user), {})
                current_budget = user_data.get("max_budget", 0) or 0
                current_spend = user_data.get("spend", 0)
                current_tpm = user_data.get("tpm_limit", 0) or 0
                current_rpm = user_data.get("rpm_limit", 0) or 0

                # Show current status
                info_col1, info_col2, info_col3 = st.columns(3)
                with info_col1:
                    st.write(f"**Current Spend:** ${current_spend:.4f}")
                with info_col2:
                    st.write(f"**Current Budget:** ${current_budget}")
                with info_col3:
                    if current_budget > 0:
                        pct = (current_spend / current_budget) * 100
                        st.write(f"**Usage:** {pct:.1f}%")

                # Show lifetime spend from audit
                summary = spend_tracker.get_user_summary(selected_user)
                if summary["total_resets"] > 0:
                    lifetime = summary["lifetime_spend"] + current_spend
                    st.info(
                        f"📊 Lifetime: ${lifetime:.4f} across {summary['total_resets']} resets | "
                        f"Last reset: {summary['last_reset']}"
                    )

                with st.form("update_user_budget_form"):
                    new_budget = st.number_input(
                        "Monthly Budget (USD)",
                        min_value=0.0, value=float(current_budget), step=10.0
                    )
                    new_tpm = st.number_input(
                        "TPM Limit", min_value=0, value=int(current_tpm), step=10000
                    )
                    new_rpm = st.number_input(
                        "RPM Limit", min_value=0, value=int(current_rpm), step=5
                    )

                    current_models = user_data.get("models", [])
                    valid_defaults = [m for m in current_models if m in AVAILABLE_MODELS]
                    new_models = st.multiselect(
                        "Allowed Models", AVAILABLE_MODELS, default=valid_defaults
                    )

                    submitted = st.form_submit_button("🔄 Update Limits", type="primary")
                    if submitted:
                        try:
                            client.update_user(
                                selected_user,
                                max_budget=new_budget,
                                tpm_limit=new_tpm,
                                rpm_limit=new_rpm,
                                models=new_models
                            )
                            st.success(f"✅ Limits updated for {selected_user}")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to update: {e}")

    except Exception as e:
        st.error(f"Error: {e}")

# ========== TAB 2: Per-Team Limits ==========
with tab2:
    st.subheader("Per-Team Budget Limits")
    try:
        teams = client.list_teams()
        if not teams:
            st.info("No teams found.")
        else:
            team_table_data = []
            for team in teams:
                team_table_data.append({
                    "Team": team.get("team_alias", team.get("team_id", "")),
                    "Spend ($)": round(team.get("spend", 0), 2),
                    "Budget ($)": team.get("max_budget", "Unlimited"),
                    "TPM Limit": team.get("tpm_limit", "Unlimited"),
                    "Models": ", ".join(team.get("models", [])) or "All"
                })

            df = pd.DataFrame(team_table_data)
            st.dataframe(df, use_container_width=True, hide_index=True)

            st.divider()
            st.write("### Modify Team Limits")

            team_options = {t.get("team_alias", t.get("team_id", "")): t.get("team_id", "") for t in teams}
            selected_team_name = st.selectbox("Select Team", list(team_options.keys()))
            selected_team_id = team_options[selected_team_name]
            team_data_selected = next((t for t in teams if t.get("team_id") == selected_team_id), {})

            with st.form("update_team_budget_form"):
                new_team_budget = st.number_input(
                    "Team Budget (USD)", min_value=0.0,
                    value=float(team_data_selected.get("max_budget", 0) or 0), step=50.0
                )
                new_team_tpm = st.number_input(
                    "Team TPM Limit", min_value=0,
                    value=int(team_data_selected.get("tpm_limit", 0) or 0), step=50000
                )
                new_team_rpm = st.number_input(
                    "Team RPM Limit", min_value=0,
                    value=int(team_data_selected.get("rpm_limit", 0) or 0), step=10
                )

                current_team_models = team_data_selected.get("models", [])
                valid_defaults = [m for m in current_team_models if m in AVAILABLE_MODELS]
                new_team_models = st.multiselect(
                    "Allowed Models", AVAILABLE_MODELS,
                    default=valid_defaults, key="team_models_update"
                )

                submitted = st.form_submit_button("🔄 Update Team Limits", type="primary")
                if submitted:
                    try:
                        client.update_team(
                            selected_team_id,
                            max_budget=new_team_budget,
                            tpm_limit=new_team_tpm,
                            rpm_limit=new_team_rpm,
                            models=new_team_models
                        )
                        st.success(f"✅ Team '{selected_team_name}' updated!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed: {e}")

    except Exception as e:
        st.error(f"Error: {e}")

# ========== TAB 3: Bulk Actions ==========
with tab3:
    st.subheader("⚡ Bulk Budget Actions")
    st.warning("⚠️ These actions affect ALL users. Use with caution.")

    col1, col2 = st.columns(2)

    # --- Increase All Budgets ---
    with col1:
        st.write("### 📈 Increase All User Budgets")
        increase_type = st.radio("Increase by", ["Percentage (%)", "Fixed Amount ($)"], key="increase_type")

        if increase_type == "Percentage (%)":
            increase_pct = st.number_input("Percentage", min_value=0, value=20, step=5)
        else:
            increase_amount = st.number_input("Amount ($)", min_value=0.0, value=10.0, step=5.0)

        if st.button("📈 Apply Increase", type="primary"):
            try:
                users = client.list_users()
                updated = 0
                for user in users:
                    current = user.get("max_budget", 0) or 0
                    if current > 0:
                        if increase_type == "Percentage (%)":
                            new_val = current * (1 + increase_pct / 100)
                        else:
                            new_val = current + increase_amount
                        client.update_user(user["user_id"], max_budget=round(new_val, 2))
                        updated += 1
                st.success(f"✅ Updated budgets for {updated} users!")
            except Exception as e:
                st.error(f"Failed: {e}")

    # --- Reset All Spend ---
    with col2:
        st.write("### 🔄 Reset All Spend Counters")
        st.write("Resets current spend for ALL users to $0.")
        st.caption("🛡️ All spend values are recorded in audit history before reset.")

        confirm_reset = st.checkbox("I understand this resets ALL user spend counters")

        if confirm_reset:
            try:
                users = client.list_users()
                users_with_spend = [u for u in users if u.get("spend", 0) > 0]
                if users_with_spend:
                    total_to_reset = sum(u.get("spend", 0) for u in users_with_spend)
                    st.info(
                        f"📋 **Preview:** {len(users_with_spend)} users | "
                        f"${total_to_reset:.4f} total will be recorded in audit"
                    )
                else:
                    st.info("All users already at $0.")
            except Exception:
                pass

        if st.button("🔄 Reset All Spend", type="primary", disabled=not confirm_reset):
            try:
                users = client.list_users()
                reset_count = 0
                audit_total = 0
                failed_users = []

                progress_bar = st.progress(0)
                status_text = st.empty()

                for i, user in enumerate(users):
                    user_id = user.get("user_id", "")
                    current_spend = user.get("spend", 0)

                    if current_spend > 0:
                        try:
                            spend_tracker.record_reset(
                                user_id=user_id,
                                spend_before_reset=current_spend,
                                reset_by="admin_bulk",
                                notes="Bulk reset from Budget Controls"
                            )
                            client.reset_user_budget(user_id)
                            reset_count += 1
                            audit_total += current_spend
                        except Exception as user_err:
                            failed_users.append({"user": user_id, "error": str(user_err)})

                    progress_bar.progress((i + 1) / len(users))
                    status_text.text(f"Processing {i + 1}/{len(users)}...")

                progress_bar.empty()
                status_text.empty()

                st.success(
                    f"✅ Bulk reset complete!\n\n"
                    f"- **{reset_count}** users reset to $0\n"
                    f"- **${audit_total:.4f}** recorded in audit history"
                )

                if failed_users:
                    st.warning(f"⚠️ {len(failed_users)} failed:")
                    for f in failed_users:
                        st.write(f"  - `{f['user']}`: {f['error']}")

            except Exception as e:
                st.error(f"Failed: {e}")

    st.divider()

    # --- Uniform Budget ---
    st.write("### 💰 Set Uniform Budget for All Users")
    uniform_budget = st.number_input(
        "Set all users to this budget ($)",
        min_value=0.0, value=DEFAULTS["user_budget"], step=10.0
    )
    if st.button("💰 Apply Uniform Budget"):
        try:
            users = client.list_users()
            for user in users:
                client.update_user(user["user_id"], max_budget=uniform_budget)
            st.success(f"✅ All {len(users)} users set to ${uniform_budget}/month")
        except Exception as e:
            st.error(f"Failed: {e}")

    st.divider()

    # --- Audit Summary ---
    st.write("### 📜 Reset Audit Summary")
    try:
        all_summaries = spend_tracker.get_all_users_summary()
        if all_summaries:
            total_resets_all = sum(s["total_resets"] for s in all_summaries)
            total_lifetime_all = sum(s["lifetime_spend"] for s in all_summaries)

            mcol1, mcol2, mcol3 = st.columns(3)
            with mcol1:
                st.metric("Total Resets (All Users)", total_resets_all)
            with mcol2:
                st.metric("Total Spend in Audit", f"${total_lifetime_all:.2f}")
            with mcol3:
                st.metric("Users With History", len(all_summaries))

            recent_data = []
            for s in sorted(all_summaries, key=lambda x: x["last_reset"], reverse=True)[:10]:
                recent_data.append({
                    "User": s["user_id"],
                    "Resets": s["total_resets"],
                    "Lifetime ($)": round(s["lifetime_spend"], 4),
                    "Last Reset": s["last_reset"]
                })
            st.dataframe(pd.DataFrame(recent_data), use_container_width=True, hide_index=True)
            st.caption("📊 Full details on the **Spend Audit History** page.")
        else:
            st.info("No reset history yet.")
    except Exception as e:
        st.error(f"Error: {e}")

