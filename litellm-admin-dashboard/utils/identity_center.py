"""
litellm-admin-dashboard/utils/identity_center.py

AWS IAM Identity Center client for bi-directional user and group sync.

What it does:
  - Wraps the AWS identitystore boto3 client with convenience methods used
    across the User Management and Group Management dashboard pages.
  - Read operations: list all users, list all groups, get group members,
    look up a user by username, look up a group by name.
  - Write operations: create users, delete users, create groups, delete groups,
    add a user to a group, remove a user from a group, move a user between groups.
  - Every write operation that originates in the dashboard is mirrored to
    Identity Center so the company's SSO directory stays in sync with LiteLLM.

Why this exists:
  Companies running AWS SSO/IAM Identity Center already have their team
  membership defined there. This client means admins can import those groups
  into LiteLLM in one click (IC → LiteLLM) or create a team in the dashboard
  and have it appear in Identity Center automatically (LiteLLM → IC).

Environment variables consumed:
  IDENTITY_STORE_ID  — Identity Store ID from the IAM Identity Center console
                       (e.g. d-9f67525912). Required; raises ValueError if absent.
  AWS_REGION_NAME    — AWS region for the identitystore API (default: ap-south-1).

Authentication: uses the EC2/ECS instance profile or ambient AWS credentials —
no long-lived access keys are stored.
"""
import os
import boto3
from typing import List, Dict, Optional


class IdentityCenterClient:
    """Client for AWS IAM Identity Center (SSO) user and group operations."""

    def __init__(self):
        self.identity_store_id = os.environ.get("IDENTITY_STORE_ID", "")
        self.region = os.environ.get("AWS_REGION_NAME", "ap-south-1")

        if not self.identity_store_id:
            raise ValueError(
                "IDENTITY_STORE_ID environment variable is not set. "
                "Set it to your Identity Store ID (e.g., d-xxxxxxxxxx)"
            )

        self.client = boto3.client(
            "identitystore",
            region_name=self.region
        )

    # ==================== READ OPERATIONS ====================

    def list_users(self) -> List[Dict]:
        """Fetch all users from IAM Identity Center."""
        users = []
        paginator = self.client.get_paginator("list_users")

        for page in paginator.paginate(IdentityStoreId=self.identity_store_id):
            for user in page.get("Users", []):
                # Extract primary email
                email = ""
                for email_obj in user.get("Emails", []):
                    if email_obj.get("Primary", False):
                        email = email_obj.get("Value", "")
                        break
                if not email and user.get("Emails"):
                    email = user["Emails"][0].get("Value", "")

                users.append({
                    "user_id": user.get("UserId", ""),
                    "username": user.get("UserName", ""),
                    "display_name": user.get("DisplayName", ""),
                    "email": email,
                    "first_name": user.get("Name", {}).get("GivenName", ""),
                    "last_name": user.get("Name", {}).get("FamilyName", ""),
                })

        return users

    def list_groups(self) -> List[Dict]:
        """Fetch all groups from IAM Identity Center."""
        groups = []
        paginator = self.client.get_paginator("list_groups")

        for page in paginator.paginate(IdentityStoreId=self.identity_store_id):
            for group in page.get("Groups", []):
                groups.append({
                    "group_id": group.get("GroupId", ""),
                    "display_name": group.get("DisplayName", ""),
                    "description": group.get("Description", ""),
                })

        return groups

    def get_group_members(self, group_id: str) -> List[Dict]:
        """Get all members of a specific group."""
        members = []
        paginator = self.client.get_paginator("list_group_memberships")

        for page in paginator.paginate(
            IdentityStoreId=self.identity_store_id,
            GroupId=group_id
        ):
            for membership in page.get("GroupMemberships", []):
                member_id = membership.get("MemberId", {}).get("UserId", "")
                membership_id = membership.get("MembershipId", "")
                if member_id:
                    # Fetch user details
                    try:
                        user = self.client.describe_user(
                            IdentityStoreId=self.identity_store_id,
                            UserId=member_id
                        )
                        email = ""
                        for email_obj in user.get("Emails", []):
                            if email_obj.get("Primary", False):
                                email = email_obj.get("Value", "")
                                break

                        members.append({
                            "user_id": member_id,
                            "username": user.get("UserName", ""),
                            "display_name": user.get("DisplayName", ""),
                            "email": email,
                            "membership_id": membership_id,
                        })
                    except Exception:
                        members.append({
                            "user_id": member_id,
                            "username": member_id,
                            "display_name": "",
                            "email": "",
                            "membership_id": membership_id,
                        })

        return members

    def get_user_by_username(self, username: str) -> Optional[Dict]:
        """Find a user in Identity Center by username."""
        try:
            response = self.client.list_users(
                IdentityStoreId=self.identity_store_id,
                Filters=[{
                    "AttributePath": "UserName",
                    "AttributeValue": username
                }]
            )
            users = response.get("Users", [])
            if users:
                user = users[0]
                email = ""
                for email_obj in user.get("Emails", []):
                    if email_obj.get("Primary", False):
                        email = email_obj.get("Value", "")
                        break
                return {
                    "user_id": user.get("UserId", ""),
                    "username": user.get("UserName", ""),
                    "display_name": user.get("DisplayName", ""),
                    "email": email,
                }
            return None
        except Exception:
            return None

    def get_group_by_name(self, group_name: str) -> Optional[Dict]:
        """Find a group in Identity Center by display name."""
        try:
            response = self.client.list_groups(
                IdentityStoreId=self.identity_store_id,
                Filters=[{
                    "AttributePath": "DisplayName",
                    "AttributeValue": group_name
                }]
            )
            groups = response.get("Groups", [])
            if groups:
                group = groups[0]
                return {
                    "group_id": group.get("GroupId", ""),
                    "display_name": group.get("DisplayName", ""),
                    "description": group.get("Description", ""),
                }
            return None
        except Exception:
            return None

    def get_user_groups(self, user_id: str) -> List[Dict]:
        """Get all groups a user belongs to."""
        groups = []
        try:
            paginator = self.client.get_paginator("list_group_memberships_for_member")
            for page in paginator.paginate(
                IdentityStoreId=self.identity_store_id,
                MemberId={"UserId": user_id}
            ):
                for membership in page.get("GroupMemberships", []):
                    group_id = membership.get("GroupId", "")
                    membership_id = membership.get("MembershipId", "")
                    # Get group details
                    try:
                        group = self.client.describe_group(
                            IdentityStoreId=self.identity_store_id,
                            GroupId=group_id
                        )
                        groups.append({
                            "group_id": group_id,
                            "display_name": group.get("DisplayName", ""),
                            "membership_id": membership_id,
                        })
                    except Exception:
                        groups.append({
                            "group_id": group_id,
                            "display_name": group_id,
                            "membership_id": membership_id,
                        })
        except Exception:
            pass
        return groups

    # ==================== WRITE OPERATIONS ====================

    def create_user(self, username: str, first_name: str, last_name: str,
                    email: str, display_name: str = None) -> Dict:
        """Create a new user in IAM Identity Center."""
        if not display_name:
            display_name = f"{first_name} {last_name}"

        try:
            response = self.client.create_user(
                IdentityStoreId=self.identity_store_id,
                UserName=username,
                Name={
                    "GivenName": first_name,
                    "FamilyName": last_name
                },
                DisplayName=display_name,
                Emails=[{
                    "Value": email,
                    "Type": "Work",
                    "Primary": True
                }]
            )
            return {
                "user_id": response.get("UserId", ""),
                "username": username,
                "display_name": display_name,
                "email": email,
            }
        except self.client.exceptions.ConflictException:
            raise Exception(f"User '{username}' already exists in Identity Center.")
        except Exception as e:
            raise Exception(f"Failed to create user in Identity Center: {str(e)}")

    def delete_user(self, user_id: str) -> bool:
        """Delete a user from IAM Identity Center."""
        try:
            self.client.delete_user(
                IdentityStoreId=self.identity_store_id,
                UserId=user_id
            )
            return True
        except Exception as e:
            raise Exception(f"Failed to delete user from Identity Center: {str(e)}")

    def create_group(self, group_name: str, description: str = "") -> Dict:
        """Create a new group in IAM Identity Center."""
        try:
            response = self.client.create_group(
                IdentityStoreId=self.identity_store_id,
                DisplayName=group_name,
                Description=description or f"Team: {group_name}"
            )
            return {
                "group_id": response.get("GroupId", ""),
                "display_name": group_name,
                "description": description,
            }
        except self.client.exceptions.ConflictException:
            raise Exception(f"Group '{group_name}' already exists in Identity Center.")
        except Exception as e:
            raise Exception(f"Failed to create group in Identity Center: {str(e)}")

    def delete_group(self, group_id: str) -> bool:
        """Delete a group from IAM Identity Center."""
        try:
            self.client.delete_group(
                IdentityStoreId=self.identity_store_id,
                GroupId=group_id
            )
            return True
        except Exception as e:
            raise Exception(f"Failed to delete group from Identity Center: {str(e)}")

    def add_user_to_group(self, user_id: str, group_id: str) -> Dict:
        """Add a user to a group in IAM Identity Center."""
        try:
            response = self.client.create_group_membership(
                IdentityStoreId=self.identity_store_id,
                GroupId=group_id,
                MemberId={"UserId": user_id}
            )
            return {
                "membership_id": response.get("MembershipId", ""),
                "user_id": user_id,
                "group_id": group_id,
            }
        except self.client.exceptions.ConflictException:
            raise Exception("User is already a member of this group.")
        except Exception as e:
            raise Exception(f"Failed to add user to group: {str(e)}")

    def remove_user_from_group(self, membership_id: str) -> bool:
        """Remove a user from a group using the membership ID."""
        try:
            self.client.delete_group_membership(
                IdentityStoreId=self.identity_store_id,
                MembershipId=membership_id
            )
            return True
        except Exception as e:
            raise Exception(f"Failed to remove user from group: {str(e)}")

    def move_user_between_groups(self, user_id: str, from_group_id: str,
                                  to_group_id: str) -> Dict:
        """Move a user from one group to another."""
        # Find membership ID for current group
        members = self.get_group_members(from_group_id)
        membership_id = None
        for member in members:
            if member["user_id"] == user_id:
                membership_id = member.get("membership_id", "")
                break

        if not membership_id:
            raise Exception("User is not a member of the source group.")

        # Remove from old group
        self.remove_user_from_group(membership_id)

        # Add to new group
        result = self.add_user_to_group(user_id, to_group_id)

        return {
            "user_id": user_id,
            "from_group": from_group_id,
            "to_group": to_group_id,
            "new_membership_id": result["membership_id"],
        }

    def get_membership_id(self, user_id: str, group_id: str) -> Optional[str]:
        """Get the membership ID for a user in a specific group."""
        try:
            paginator = self.client.get_paginator("list_group_memberships")
            for page in paginator.paginate(
                IdentityStoreId=self.identity_store_id,
                GroupId=group_id
            ):
                for membership in page.get("GroupMemberships", []):
                    member_user_id = membership.get("MemberId", {}).get("UserId", "")
                    if member_user_id == user_id:
                        return membership.get("MembershipId", "")
        except Exception:
            pass
        return None


