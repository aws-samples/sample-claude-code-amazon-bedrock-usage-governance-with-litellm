"""
litellm-admin-dashboard/pages/4_Usage_Dashboard.py

Streamlit page: Usage Dashboard.

What it does:
  - Shows five top-level KPI metrics at a glance: total month-to-date spend,
    total user count, active users (spend > $0), blocked users (spend >= budget),
    and average spend per user.
  - Per-User Spend Breakdown: sortable table showing each user's current spend,
    budget cap, percentage used, and a colour-coded status (green / yellow
    warning at 80% / red blocked at 100%).  Three summary counters below the
    table aggregate how many users are in each state.
  - Team Spend Summary: table of every team with member count, spend, budget,
    average spend per member, and status indicator — giving ops teams a fast
    view of which teams are burning through budget.

Data source: live queries to the LiteLLM proxy API via LiteLLMClient on every
page load. No caching — the numbers always reflect the current proxy state.

Depends on:
  utils/litellm_client.py — list_users(), list_teams() for all spend data.
"""
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from utils.litellm_client import LiteLLMClient

st.set_page_config(page_title="Usage Dashboard", page_icon="📊", layout="wide")
st.title("📊 Usage Dashboard")

client = LiteLLMClient()

# ========== Top-Level Metrics ==========
try:
    users = client.list_users()
    teams = client.list_teams()

    total_spend = sum(u.get("spend", 0) for u in users)
    active_users = sum(1 for u in users if u.get("spend", 0) > 0)
    blocked_users = sum(
        1 for u in users
        if u.get("max_budget") and u.get("max_budget", 0) > 0
        and u.get("spend", 0) >= u.get("max_budget", 0)
    )

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("💰 Total Spend (MTD)", f"${total_spend:.2f}")
    with col2:
        st.metric("👥 Total Users", len(users))
    with col3:
        st.metric("⚡ Active Users", active_users)
    with col4:
        st.metric("🚫 Blocked Users", blocked_users)
    with col5:
        avg_spend = total_spend / len(users) if users else 0
        st.metric("📈 Avg Spend/User", f"${avg_spend:.2f}")

except Exception as e:
    st.error(f"Error loading dashboard: {e}")
    st.stop()

st.divider()

# ========== Per-User Spend Breakdown ==========
st.subheader("👤 Per-User Spend Breakdown")

try:
    if users:
        user_spend_data = []
        for user in users:
            user_id = user.get("user_id", "Unknown")
            spend = user.get("spend", 0)
            max_budget = user.get("max_budget", None)

            if max_budget and max_budget > 0:
                pct_used = (spend / max_budget) * 100
            else:
                pct_used = 0

            if pct_used >= 100:
                status = "🔴 BLOCKED"
            elif pct_used >= 80:
                status = "🟡 Warning"
            else:
                status = "🟢 OK"

            user_spend_data.append({
                "User ID": user_id,
                "Email": user.get("user_email", "N/A"),
                "Team": user.get("team_id", "None"),
                "Spend ($)": round(spend, 4),
                "Budget ($)": max_budget if max_budget else "Unlimited",
                "% Used": round(pct_used, 1),
                "Status": status
            })

        df_users = pd.DataFrame(user_spend_data)
        df_users = df_users.sort_values("Spend ($)", ascending=False)
        st.dataframe(df_users, use_container_width=True, hide_index=True)

        # Status summary
        col1, col2, col3 = st.columns(3)
        with col1:
            over = sum(1 for u in user_spend_data if "BLOCKED" in u["Status"])
            st.metric("🔴 Blocked (Need Admin Reset)", over)
        with col2:
            warning = sum(1 for u in user_spend_data if "Warning" in u["Status"])
            st.metric("🟡 Approaching Limit", warning)
        with col3:
            ok = sum(1 for u in user_spend_data if "OK" in u["Status"])
            st.metric("🟢 Healthy", ok)

except Exception as e:
    st.error(f"Error loading user spend: {e}")

st.divider()

# ========== Per-User Request Log Viewer ==========
# st.subheader("📋 Per-User Request Log")

# col1, col2 = st.columns(2)
# with col1:
#     user_ids = [u.get("user_id", "") for u in users]
#     selected_log_user = st.selectbox("Select User", ["All Users"] + user_ids, key="log_user")
# with col2:
#     date_col1, date_col2 = st.columns(2)
#     with date_col1:
#         start_date = st.date_input("Start Date", value=datetime.now() - timedelta(days=7))
#     with date_col2:
#         end_date = st.date_input("End Date", value=datetime.now())

# if st.button("🔍 Load Request Logs"):
#     try:
#         spend_logs = client.get_spend_per_user(
#             start_date=start_date.strftime("%Y-%m-%d"),
#             end_date=end_date.strftime("%Y-%m-%d")
#         )

#         if spend_logs:
#             df_logs = pd.DataFrame(spend_logs)

#             if selected_log_user != "All Users":
#                 # Filter by selected user
#                 user_col = "user" if "user" in df_logs.columns else "user_id"
#                 if user_col in df_logs.columns:
#                     df_logs = df_logs[df_logs[user_col] == selected_log_user]

#             if not df_logs.empty:
#                 st.dataframe(df_logs, use_container_width=True, hide_index=True)
#                 st.write(f"**Total records:** {len(df_logs)}")
#             else:
#                 st.info("No logs found for the selected filters.")
#         else:
#             st.info("No spend logs available for the selected date range.")
#     except Exception as e:
#         st.error(f"Error loading logs: {e}")

# st.divider()

# ========== Team Spend Summary ==========
st.subheader("🏢 Team Spend Summary")

try:
    if teams:
        team_spend_data = []
        for team in teams:
            team_alias = team.get("team_alias", team.get("team_id", "Unknown"))
            spend = team.get("spend", 0)
            max_budget = team.get("max_budget", None)
            members = team.get("members_with_roles", [])

            pct = round((spend / max_budget * 100), 1) if max_budget and max_budget > 0 else 0

            team_spend_data.append({
                "Team": team_alias,
                "Members": len(members),
                "Spend ($)": round(spend, 2),
                "Budget ($)": max_budget if max_budget else "Unlimited",
                "% Used": pct,
                "Avg/Member ($)": round(spend / len(members), 2) if members else 0,
                "Status": "🔴 BLOCKED" if pct >= 100 else ("🟡" if pct >= 80 else "🟢")
            })

        df_teams = pd.DataFrame(team_spend_data)
        df_teams = df_teams.sort_values("Spend ($)", ascending=False)
        st.dataframe(df_teams, use_container_width=True, hide_index=True)
    else:
        st.info("No teams configured yet.")

except Exception as e:
    st.error(f"Error loading team data: {e}")

