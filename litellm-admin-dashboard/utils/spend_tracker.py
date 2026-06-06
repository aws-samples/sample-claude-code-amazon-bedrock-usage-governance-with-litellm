"""
litellm-admin-dashboard/utils/spend_tracker.py

Immutable audit log for all manual spend resets (users and teams).

What it does:
  - Auto-creates two PostgreSQL tables on first use:
      spend_reset_audit       — one row per user spend reset.
      team_spend_reset_audit  — one row per team spend reset.
  - Records the spend amount that was cleared, the running cumulative total
    across all resets, the reset count, the timestamp, who performed the reset,
    and an optional admin note.
  - Provides read methods for per-entity history, per-entity summary stats, and
    cross-entity summaries used by the Spend Audit History dashboard page.

Why this exists:
  LiteLLM's built-in spend counter is zeroed on reset and gives no history.
  Because this platform enforces manual-only resets (no auto budget_duration),
  every admin reset must be recorded here BEFORE calling LiteLLM so no spend
  event is ever lost — even if the LiteLLM call subsequently fails.

Key methods:
  record_reset(user_id, spend_before_reset, ...)       — log a user reset.
  record_team_reset(team_id, spend_before_reset, ...)  — log a team reset.
  get_user_history(user_id)                            — full reset log for one user.
  get_team_history(team_id)                            — full reset log for one team.
  get_all_users_summary()                              — lifetime totals for all users.
  get_all_teams_summary()                              — lifetime totals for all teams.

Environment variables consumed:
  DATABASE_URL — PostgreSQL connection string (same DB used by LiteLLM proxy).
"""
import os
import psycopg2
from datetime import datetime
from typing import Optional, List, Dict


class SpendResetTracker:
    """Tracks all spend resets with full audit history."""

    def __init__(self, database_url: str = None):
        """
        Initialize with PostgreSQL DATABASE_URL.
        Example: "postgresql://litellm_user:password@localhost:5432/litellm_db"
        """
        self.database_url = database_url or os.environ.get("DATABASE_URL", "")
        if not self.database_url:
            raise ValueError("DATABASE_URL is required for SpendResetTracker")
        self._ensure_table_exists()

    def _get_connection(self):
        return psycopg2.connect(self.database_url)

    def _ensure_table_exists(self):
        """Auto-create the audit tables if they don't exist."""
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                # User spend reset audit table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS spend_reset_audit (
                        id SERIAL PRIMARY KEY,
                        user_id VARCHAR(255) NOT NULL,
                        spend_before_reset DECIMAL(12, 6) NOT NULL,
                        cumulative_spend DECIMAL(12, 6) NOT NULL DEFAULT 0,
                        reset_count INTEGER NOT NULL DEFAULT 1,
                        reset_timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        reset_by VARCHAR(255) DEFAULT 'admin',
                        notes TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_spend_reset_user_id
                        ON spend_reset_audit(user_id);
                    CREATE INDEX IF NOT EXISTS idx_spend_reset_timestamp
                        ON spend_reset_audit(reset_timestamp);
                """)

                # Team spend reset audit table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS team_spend_reset_audit (
                        id SERIAL PRIMARY KEY,
                        team_id VARCHAR(255) NOT NULL,
                        spend_before_reset DECIMAL(12, 6) NOT NULL,
                        cumulative_spend DECIMAL(12, 6) NOT NULL DEFAULT 0,
                        reset_count INTEGER NOT NULL DEFAULT 1,
                        reset_timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        reset_by VARCHAR(255) DEFAULT 'admin',
                        notes TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_team_spend_reset_team_id
                        ON team_spend_reset_audit(team_id);
                    CREATE INDEX IF NOT EXISTS idx_team_spend_reset_timestamp
                        ON team_spend_reset_audit(reset_timestamp);
                """)
                conn.commit()
        finally:
            conn.close()

    # ==================== USER METHODS ====================

    def record_reset(self, user_id: str, spend_before_reset: float,
                     reset_by: str = "admin", notes: str = None) -> Dict:
        """
        Record a spend reset event BEFORE actually resetting in LiteLLM.
        Returns the audit record with cumulative stats.
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                # Get current cumulative spend for this user
                cur.execute("""
                    SELECT COALESCE(SUM(spend_before_reset), 0), COUNT(*)
                    FROM spend_reset_audit
                    WHERE user_id = %s
                """, (user_id,))
                row = cur.fetchone()
                previous_cumulative = float(row[0])
                previous_reset_count = row[1]

                # Calculate new cumulative
                new_cumulative = previous_cumulative + spend_before_reset
                new_reset_count = previous_reset_count + 1

                # Insert audit record
                cur.execute("""
                    INSERT INTO spend_reset_audit
                        (user_id, spend_before_reset, cumulative_spend,
                         reset_count, reset_by, notes)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id, reset_timestamp
                """, (user_id, spend_before_reset, new_cumulative,
                      new_reset_count, reset_by, notes))

                result = cur.fetchone()
                conn.commit()

                return {
                    "audit_id": result[0],
                    "user_id": user_id,
                    "spend_before_reset": spend_before_reset,
                    "cumulative_lifetime_spend": new_cumulative,
                    "total_resets": new_reset_count,
                    "reset_timestamp": result[1].isoformat()
                }
        finally:
            conn.close()

    def get_user_history(self, user_id: str) -> List[Dict]:
        """Get full reset history for a user."""
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, spend_before_reset, cumulative_spend,
                           reset_count, reset_timestamp, reset_by, notes
                    FROM spend_reset_audit
                    WHERE user_id = %s
                    ORDER BY reset_timestamp DESC
                """, (user_id,))

                rows = cur.fetchall()
                return [{
                    "id": row[0],
                    "spend_before_reset": float(row[1]),
                    "cumulative_spend": float(row[2]),
                    "reset_count": row[3],
                    "reset_timestamp": row[4].isoformat(),
                    "reset_by": row[5],
                    "notes": row[6]
                } for row in rows]
        finally:
            conn.close()

    def get_user_summary(self, user_id: str) -> Dict:
        """Get summary stats for a user."""
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        COUNT(*) as total_resets,
                        COALESCE(SUM(spend_before_reset), 0) as lifetime_spend,
                        MAX(reset_timestamp) as last_reset,
                        MIN(reset_timestamp) as first_reset
                    FROM spend_reset_audit
                    WHERE user_id = %s
                """, (user_id,))

                row = cur.fetchone()
                return {
                    "user_id": user_id,
                    "total_resets": row[0],
                    "lifetime_spend": float(row[1]),
                    "last_reset": row[2].isoformat() if row[2] else None,
                    "first_reset": row[3].isoformat() if row[3] else None
                }
        finally:
            conn.close()

    def get_all_users_summary(self) -> List[Dict]:
        """Get summary for all users who have had resets."""
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        user_id,
                        COUNT(*) as total_resets,
                        SUM(spend_before_reset) as lifetime_spend,
                        MAX(reset_timestamp) as last_reset
                    FROM spend_reset_audit
                    GROUP BY user_id
                    ORDER BY lifetime_spend DESC
                """)

                rows = cur.fetchall()
                return [{
                    "user_id": row[0],
                    "total_resets": row[1],
                    "lifetime_spend": float(row[2]),
                    "last_reset": row[3].isoformat()
                } for row in rows]
        finally:
            conn.close()

    # ==================== TEAM METHODS ====================

    def record_team_reset(self, team_id: str, spend_before_reset: float,
                          reset_by: str = "admin", notes: str = None) -> Dict:
        """
        Record a team spend reset event BEFORE actually resetting in LiteLLM.
        Returns the audit record with cumulative stats.
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                # Get current cumulative spend for this team
                cur.execute("""
                    SELECT COALESCE(SUM(spend_before_reset), 0), COUNT(*)
                    FROM team_spend_reset_audit
                    WHERE team_id = %s
                """, (team_id,))
                row = cur.fetchone()
                previous_cumulative = float(row[0])
                previous_reset_count = row[1]

                # Calculate new cumulative
                new_cumulative = previous_cumulative + spend_before_reset
                new_reset_count = previous_reset_count + 1

                # Insert audit record
                cur.execute("""
                    INSERT INTO team_spend_reset_audit
                        (team_id, spend_before_reset, cumulative_spend,
                         reset_count, reset_by, notes)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id, reset_timestamp
                """, (team_id, spend_before_reset, new_cumulative,
                      new_reset_count, reset_by, notes))

                result = cur.fetchone()
                conn.commit()

                return {
                    "audit_id": result[0],
                    "team_id": team_id,
                    "spend_before_reset": spend_before_reset,
                    "cumulative_lifetime_spend": new_cumulative,
                    "total_resets": new_reset_count,
                    "reset_timestamp": result[1].isoformat()
                }
        finally:
            conn.close()

    def get_team_history(self, team_id: str) -> List[Dict]:
        """Get full reset history for a team."""
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, spend_before_reset, cumulative_spend,
                           reset_count, reset_timestamp, reset_by, notes
                    FROM team_spend_reset_audit
                    WHERE team_id = %s
                    ORDER BY reset_timestamp DESC
                """, (team_id,))

                rows = cur.fetchall()
                return [{
                    "id": row[0],
                    "spend_before_reset": float(row[1]),
                    "cumulative_spend": float(row[2]),
                    "reset_count": row[3],
                    "reset_timestamp": row[4].isoformat(),
                    "reset_by": row[5],
                    "notes": row[6]
                } for row in rows]
        finally:
            conn.close()

    def get_team_summary(self, team_id: str) -> Dict:
        """Get summary stats for a team."""
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        COUNT(*) as total_resets,
                        COALESCE(SUM(spend_before_reset), 0) as lifetime_spend,
                        MAX(reset_timestamp) as last_reset,
                        MIN(reset_timestamp) as first_reset
                    FROM team_spend_reset_audit
                    WHERE team_id = %s
                """, (team_id,))

                row = cur.fetchone()
                return {
                    "team_id": team_id,
                    "total_resets": row[0],
                    "lifetime_spend": float(row[1]),
                    "last_reset": row[2].isoformat() if row[2] else None,
                    "first_reset": row[3].isoformat() if row[3] else None
                }
        finally:
            conn.close()

    def get_all_teams_summary(self) -> List[Dict]:
        """Get summary for all teams that have had resets."""
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        team_id,
                        COUNT(*) as total_resets,
                        SUM(spend_before_reset) as lifetime_spend,
                        MAX(reset_timestamp) as last_reset
                    FROM team_spend_reset_audit
                    GROUP BY team_id
                    ORDER BY lifetime_spend DESC
                """)

                rows = cur.fetchall()
                return [{
                    "team_id": row[0],
                    "total_resets": row[1],
                    "lifetime_spend": float(row[2]),
                    "last_reset": row[3].isoformat()
                } for row in rows]
        finally:
            conn.close()
