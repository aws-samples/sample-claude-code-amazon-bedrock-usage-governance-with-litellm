"""
litellm-admin-dashboard/pages/6_Spend_Audit_History.py

Streamlit page: Spend Audit History.

What it does:
  - Tab 1 — Overview: aggregated lifetime spend for all users and teams,
    combining current active spend with all historical spend from past resets.
    This is the true total cost — not just the current billing cycle.
    Includes CSV download buttons for both user and team reports.
  - Tab 2 — Per-User History: drill-down for a single user showing every reset
    event (reset number, timestamp, spend cleared, running cumulative total,
    who reset it, and any admin note), plus a bar chart of spend per cycle.
  - Tab 3 — Per-Team History: same drill-down at the team level.
  - Tab 4 — User Analytics: top-10 lifetime spenders, most-frequently-reset
    users, and a budget efficiency table recommending whether to raise or lower
    each user's budget based on average spend per cycle vs their allocation.
  - Tab 5 — Team Analytics: same analytics views at the team level.

Why this page exists:
  LiteLLM's native spend counter is zeroed on every admin reset, making it
  impossible to answer "how much has this user spent in total since onboarding?"
  This page reconstructs true lifetime spend by summing the SpendResetTracker
  audit records (spend_before_reset per cycle) with the user's current active
  spend, giving finance and security teams a complete and tamper-evident picture.

Depends on:
  utils/litellm_client.py  — current spend from list_users() / list_teams().
  utils/spend_tracker.py   — historical reset records from PostgreSQL audit tables.
"""
import streamlit as st
import pandas as pd
from datetime import datetime
from utils.litellm_client import LiteLLMClient
from utils.spend_tracker import SpendResetTracker
import os

st.set_page_config(page_title="Spend Audit History", page_icon="📜", layout="wide")
st.title("📜 Spend Audit History")

client = LiteLLMClient()
spend_tracker = SpendResetTracker(os.environ.get("DATABASE_URL"))

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 Overview",
    "🔍 Per-User History",
    "🏢 Per-Team History",
    "📈 User Analytics",
    "📈 Team Analytics"
])

# ========== TAB 1: Overview ==========
with tab1:
    st.subheader("Lifetime Spend Summary (Across All Resets)")

    try:
        users = client.list_users()
        teams = client.list_teams()
        all_summaries = spend_tracker.get_all_users_summary()
        all_team_summaries = spend_tracker.get_all_teams_summary()

        # User metrics
        total_lifetime_spend = sum(s["lifetime_spend"] for s in all_summaries)
        total_resets = sum(s["total_resets"] for s in all_summaries)
        users_with_resets = len(all_summaries)
        current_total_spend = sum(u.get("spend", 0) for u in users)

        # Team metrics
        total_team_lifetime_spend = sum(s["lifetime_spend"] for s in all_team_summaries)
        total_team_resets = sum(s["total_resets"] for s in all_team_summaries)
        teams_with_resets = len(all_team_summaries)
        current_team_spend = sum(t.get("spend", 0) for t in teams)

        st.write("### 👥 User Spend Summary")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric(
                "💰 Total Lifetime Spend",
                f"${total_lifetime_spend + current_total_spend:.2f}",
                help="All spend ever: past resets + current active spend"
            )
        with col2:
            st.metric("🔄 Total Resets", total_resets)
        with col3:
            st.metric("👥 Users With Resets", users_with_resets)
        with col4:
            avg = (total_lifetime_spend + current_total_spend) / len(users) if users else 0
            st.metric("📊 Avg Lifetime/User", f"${avg:.2f}")

        st.divider()

        st.write("### 🏢 Team Spend Summary")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric(
                "💰 Total Team Lifetime Spend",
                f"${total_team_lifetime_spend + current_team_spend:.2f}",
                help="All team spend ever: past resets + current active spend"
            )
        with col2:
            st.metric("🔄 Total Team Resets", total_team_resets)
        with col3:
            st.metric("🏢 Teams With Resets", teams_with_resets)
        with col4:
            avg_team = (total_team_lifetime_spend + current_team_spend) / len(teams) if teams else 0
            st.metric("📊 Avg Lifetime/Team", f"${avg_team:.2f}")

        st.divider()

        # Combined user report table
        st.write("### 💳 Complete User Spend Report")
        st.caption("Current spend + all historical spend from resets = true lifetime cost per user")

        combined_data = []
        audit_lookup = {s["user_id"]: s for s in all_summaries}

        for user in users:
            user_id = user.get("user_id", "Unknown")
            current_spend = user.get("spend", 0)
            max_budget = user.get("max_budget", None)

            audit_info = audit_lookup.get(user_id, {})
            lifetime_from_resets = audit_info.get("lifetime_spend", 0)
            total_resets_user = audit_info.get("total_resets", 0)
            last_reset = audit_info.get("last_reset", "Never")

            total_lifetime = lifetime_from_resets + current_spend

            combined_data.append({
                "User ID": user_id,
                "Current Spend ($)": round(current_spend, 4),
                "Budget ($)": max_budget if max_budget else "Unlimited",
                "Past Resets Spend ($)": round(lifetime_from_resets, 4),
                "Total Lifetime ($)": round(total_lifetime, 4),
                "Resets": total_resets_user,
                "Last Reset": last_reset if last_reset != "Never" else "Never"
            })

        df_combined = pd.DataFrame(combined_data)
        df_combined = df_combined.sort_values("Total Lifetime ($)", ascending=False)
        st.dataframe(df_combined, use_container_width=True, hide_index=True)

        st.divider()

        # Combined team report table
        st.write("### 🏢 Complete Team Spend Report")
        st.caption("Current team spend + all historical spend from resets = true lifetime cost per team")

        team_combined_data = []
        team_audit_lookup = {s["team_id"]: s for s in all_team_summaries}

        for team in teams:
            team_id = team.get("team_id", "Unknown")
            team_alias = team.get("team_alias", "Unnamed")
            current_spend = team.get("spend", 0)
            max_budget = team.get("max_budget", None)

            audit_info = team_audit_lookup.get(team_id, {})
            lifetime_from_resets = audit_info.get("lifetime_spend", 0)
            total_resets_team = audit_info.get("total_resets", 0)
            last_reset = audit_info.get("last_reset", "Never")

            total_lifetime = lifetime_from_resets + current_spend

            team_combined_data.append({
                "Team Name": team_alias,
                "Team ID": team_id,
                "Current Spend ($)": round(current_spend, 4),
                "Budget ($)": max_budget if max_budget else "Unlimited",
                "Past Resets Spend ($)": round(lifetime_from_resets, 4),
                "Total Lifetime ($)": round(total_lifetime, 4),
                "Resets": total_resets_team,
                "Last Reset": last_reset if last_reset != "Never" else "Never"
            })

        df_team_combined = pd.DataFrame(team_combined_data)
        if not df_team_combined.empty:
            df_team_combined = df_team_combined.sort_values("Total Lifetime ($)", ascending=False)
        st.dataframe(df_team_combined, use_container_width=True, hide_index=True)

        # Export buttons
        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                label="📥 Export User Report as CSV",
                data=df_combined.to_csv(index=False),
                file_name=f"user_spend_audit_report_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                key="export_user_csv"
            )
        with col2:
            if not df_team_combined.empty:
                st.download_button(
                    label="📥 Export Team Report as CSV",
                    data=df_team_combined.to_csv(index=False),
                    file_name=f"team_spend_audit_report_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv",
                    key="export_team_csv"
                )

    except Exception as e:
        st.error(f"Error loading overview: {e}")

# ========== TAB 2: Per-User History ==========
with tab2:
    st.subheader("🔍 Per-User Reset History")

    try:
        users = client.list_users()
        user_ids = [u.get("user_id", "") for u in users]
        selected_user = st.selectbox("Select User", user_ids, key="audit_user_select")

        if selected_user:
            summary = spend_tracker.get_user_summary(selected_user)
            user_data = next((u for u in users if u.get("user_id") == selected_user), {})
            current_spend = user_data.get("spend", 0)

            # Summary cards
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Current Spend", f"${current_spend:.4f}")
            with col2:
                st.metric("Total Resets", summary["total_resets"])
            with col3:
                total_lifetime = summary["lifetime_spend"] + current_spend
                st.metric("Lifetime Spend", f"${total_lifetime:.4f}")
            with col4:
                if summary["last_reset"]:
                    last_reset_dt = datetime.fromisoformat(summary["last_reset"])
                    days_since = (datetime.now(last_reset_dt.tzinfo) - last_reset_dt).days
                    st.metric("Days Since Reset", days_since)
                else:
                    st.metric("Days Since Reset", "N/A")

            st.divider()

            # Full history
            history = spend_tracker.get_user_history(selected_user)

            if history:
                st.write(f"### Reset History for `{selected_user}`")

                history_data = []
                for record in history:
                    history_data.append({
                        "Reset #": record["reset_count"],
                        "Date & Time": record["reset_timestamp"],
                        "Spend Before Reset ($)": round(record["spend_before_reset"], 4),
                        "Cumulative ($)": round(record["cumulative_spend"], 4),
                        "Reset By": record["reset_by"],
                        "Notes": record["notes"] or "-"
                    })

                df_history = pd.DataFrame(history_data)
                st.dataframe(df_history, use_container_width=True, hide_index=True)

                # Bar chart of spend per cycle
                st.write("### 📊 Spend Per Reset Cycle")
                chart_data = pd.DataFrame({
                    "Reset #": [h["reset_count"] for h in history],
                    "Spend ($)": [h["spend_before_reset"] for h in history]
                }).sort_values("Reset #")
                st.bar_chart(chart_data.set_index("Reset #"))

            else:
                st.info(f"No reset history for {selected_user}. Spend has never been reset.")

    except Exception as e:
        st.error(f"Error: {e}")

# ========== TAB 3: Per-Team History ==========
with tab3:
    st.subheader("🏢 Per-Team Reset History")

    try:
        teams = client.list_teams()

        if not teams:
            st.info("No teams found.")
        else:
            team_options = {t.get("team_alias", t.get("team_id", "")): t.get("team_id", "") for t in teams}
            selected_team_name = st.selectbox(
                "Select Team",
                list(team_options.keys()),
                key="audit_team_select"
            )

            if selected_team_name:
                selected_team_id = team_options[selected_team_name]
                team_data = next((t for t in teams if t.get("team_id") == selected_team_id), {})
                current_spend = team_data.get("spend", 0)
                max_budget = team_data.get("max_budget", None)
                members = team_data.get("members_with_roles", [])

                summary = spend_tracker.get_team_summary(selected_team_id)

                # Summary cards
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Current Spend", f"${current_spend:.4f}")
                with col2:
                    st.metric("Total Resets", summary["total_resets"])
                with col3:
                    total_lifetime = summary["lifetime_spend"] + current_spend
                    st.metric("Lifetime Spend", f"${total_lifetime:.4f}")
                with col4:
                    if summary["last_reset"]:
                        last_reset_dt = datetime.fromisoformat(summary["last_reset"])
                        days_since = (datetime.now(last_reset_dt.tzinfo) - last_reset_dt).days
                        st.metric("Days Since Reset", days_since)
                    else:
                        st.metric("Days Since Reset", "N/A")

                # Team info
                st.divider()
                col1, col2 = st.columns(2)
                with col1:
                    st.write(f"**Team ID:** {selected_team_id}")
                    st.write(f"**Budget:** ${max_budget}" if max_budget else "**Budget:** Unlimited")
                with col2:
                    st.write(f"**Members:** {len(members)}")
                    if members:
                        member_list = ", ".join([m.get("user_id", "Unknown") for m in members])
                        st.write(f"**Member List:** {member_list}")

                st.divider()

                # Full history
                history = spend_tracker.get_team_history(selected_team_id)

                if history:
                    st.write(f"### Reset History for `{selected_team_name}`")

                    history_data = []
                    for record in history:
                        history_data.append({
                            "Reset #": record["reset_count"],
                            "Date & Time": record["reset_timestamp"],
                            "Spend Before Reset ($)": round(record["spend_before_reset"], 4),
                            "Cumulative ($)": round(record["cumulative_spend"], 4),
                            "Reset By": record["reset_by"],
                            "Notes": record["notes"] or "-"
                        })

                    df_history = pd.DataFrame(history_data)
                    st.dataframe(df_history, use_container_width=True, hide_index=True)

                    # Bar chart of spend per cycle
                    st.write("### 📊 Team Spend Per Reset Cycle")
                    chart_data = pd.DataFrame({
                        "Reset #": [h["reset_count"] for h in history],
                        "Spend ($)": [h["spend_before_reset"] for h in history]
                    }).sort_values("Reset #")
                    st.bar_chart(chart_data.set_index("Reset #"))

                else:
                    st.info(f"No reset history for team '{selected_team_name}'. Spend has never been reset.")

    except Exception as e:
        st.error(f"Error: {e}")

# ========== TAB 4: User Analytics ==========
with tab4:
    st.subheader("📈 User Spend Analytics")

    try:
        all_summaries = spend_tracker.get_all_users_summary()
        users = client.list_users()

        if not all_summaries:
            st.info("No reset data available yet. Data appears after the first spend reset.")
        else:
            # Top spenders
            st.write("### 🏆 Top Spenders (Lifetime)")
            top_spenders = []
            for s in sorted(all_summaries, key=lambda x: x["lifetime_spend"], reverse=True)[:10]:
                user_data = next((u for u in users if u.get("user_id") == s["user_id"]), {})
                current = user_data.get("spend", 0)
                top_spenders.append({
                    "User ID": s["user_id"],
                    "Lifetime ($)": round(s["lifetime_spend"] + current, 4),
                    "Current ($)": round(current, 4),
                    "Past Resets ($)": round(s["lifetime_spend"], 4),
                    "Resets": s["total_resets"]
                })
            st.dataframe(pd.DataFrame(top_spenders), use_container_width=True, hide_index=True)

            st.divider()

            # Most frequently reset
            st.write("### 🔄 Most Frequently Reset Users")
            st.caption("Users needing frequent resets may need a budget increase.")
            freq_data = []
            for s in sorted(all_summaries, key=lambda x: x["total_resets"], reverse=True)[:10]:
                avg_per_cycle = s["lifetime_spend"] / s["total_resets"] if s["total_resets"] > 0 else 0
                freq_data.append({
                    "User ID": s["user_id"],
                    "Total Resets": s["total_resets"],
                    "Lifetime ($)": round(s["lifetime_spend"], 4),
                    "Avg $/Cycle": round(avg_per_cycle, 4),
                    "Last Reset": s["last_reset"]
                })
            st.dataframe(pd.DataFrame(freq_data), use_container_width=True, hide_index=True)

            st.divider()

            # Budget efficiency
            st.write("### 💡 Budget Efficiency Analysis")
            st.caption("Compares actual spend per cycle vs allocated budget")

            efficiency_data = []
            for user in users:
                user_id = user.get("user_id", "")
                max_budget = user.get("max_budget", 0) or 0
                current_spend = user.get("spend", 0)
                audit_info = next((s for s in all_summaries if s["user_id"] == user_id), None)

                if max_budget > 0 and audit_info and audit_info["total_resets"] > 0:
                    lifetime = audit_info["lifetime_spend"] + current_spend
                    avg_per_cycle = lifetime / (audit_info["total_resets"] + 1)
                    utilization = (avg_per_cycle / max_budget) * 100

                    if utilization < 30:
                        rec = "⬇️ Reduce budget"
                    elif utilization > 90:
                        rec = "⬆️ Increase budget"
                    else:
                        rec = "✅ Well-sized"

                    efficiency_data.append({
                        "User ID": user_id,
                        "Budget ($)": max_budget,
                        "Avg $/Cycle": round(avg_per_cycle, 4),
                        "Utilization (%)": round(utilization, 1),
                        "Recommendation": rec
                    })

            if efficiency_data:
                df_eff = pd.DataFrame(efficiency_data)
                df_eff = df_eff.sort_values("Utilization (%)", ascending=False)
                st.dataframe(df_eff, use_container_width=True, hide_index=True)
            else:
                st.info("Needs at least one reset cycle per user for analysis.")

    except Exception as e:
        st.error(f"Error: {e}")

# ========== TAB 5: Team Analytics ==========
with tab5:
    st.subheader("📈 Team Spend Analytics")

    try:
        all_team_summaries = spend_tracker.get_all_teams_summary()
        teams = client.list_teams()

        if not all_team_summaries:
            st.info("No team reset data available yet. Data appears after the first team spend reset.")
        else:
            # Top spending teams
            st.write("### 🏆 Top Spending Teams (Lifetime)")
            top_teams = []
            for s in sorted(all_team_summaries, key=lambda x: x["lifetime_spend"], reverse=True)[:10]:
                team_data = next((t for t in teams if t.get("team_id") == s["team_id"]), {})
                current = team_data.get("spend", 0)
                team_alias = team_data.get("team_alias", s["team_id"])
                top_teams.append({
                    "Team Name": team_alias,
                    "Lifetime ($)": round(s["lifetime_spend"] + current, 4),
                    "Current ($)": round(current, 4),
                    "Past Resets ($)": round(s["lifetime_spend"], 4),
                    "Resets": s["total_resets"]
                })
            st.dataframe(pd.DataFrame(top_teams), use_container_width=True, hide_index=True)

            st.divider()

            # Most frequently reset teams
            st.write("### 🔄 Most Frequently Reset Teams")
            st.caption("Teams needing frequent resets may need a budget increase.")
            freq_data = []
            for s in sorted(all_team_summaries, key=lambda x: x["total_resets"], reverse=True)[:10]:
                team_data = next((t for t in teams if t.get("team_id") == s["team_id"]), {})
                team_alias = team_data.get("team_alias", s["team_id"])
                avg_per_cycle = s["lifetime_spend"] / s["total_resets"] if s["total_resets"] > 0 else 0
                freq_data.append({
                    "Team Name": team_alias,
                    "Total Resets": s["total_resets"],
                    "Lifetime ($)": round(s["lifetime_spend"], 4),
                    "Avg $/Cycle": round(avg_per_cycle, 4),
                    "Last Reset": s["last_reset"]
                })
            st.dataframe(pd.DataFrame(freq_data), use_container_width=True, hide_index=True)

            st.divider()

            # Team budget efficiency
            st.write("### 💡 Team Budget Efficiency Analysis")
            st.caption("Compares actual team spend per cycle vs allocated budget")

            efficiency_data = []
            for team in teams:
                team_id = team.get("team_id", "")
                team_alias = team.get("team_alias", team_id)
                max_budget = team.get("max_budget", 0) or 0
                current_spend = team.get("spend", 0)
                audit_info = next((s for s in all_team_summaries if s["team_id"] == team_id), None)

                if max_budget > 0 and audit_info and audit_info["total_resets"] > 0:
                    lifetime = audit_info["lifetime_spend"] + current_spend
                    avg_per_cycle = lifetime / (audit_info["total_resets"] + 1)
                    utilization = (avg_per_cycle / max_budget) * 100

                    if utilization < 30:
                        rec = "⬇️ Reduce budget"
                    elif utilization > 90:
                        rec = "⬆️ Increase budget"
                    else:
                        rec = "✅ Well-sized"

                    efficiency_data.append({
                        "Team Name": team_alias,
                        "Budget ($)": max_budget,
                        "Avg $/Cycle": round(avg_per_cycle, 4),
                        "Utilization (%)": round(utilization, 1),
                        "Recommendation": rec
                    })

            if efficiency_data:
                df_eff = pd.DataFrame(efficiency_data)
                df_eff = df_eff.sort_values("Utilization (%)", ascending=False)
                st.dataframe(df_eff, use_container_width=True, hide_index=True)
            else:
                st.info("Needs at least one reset cycle per team for analysis.")

    except Exception as e:
        st.error(f"Error: {e}")
