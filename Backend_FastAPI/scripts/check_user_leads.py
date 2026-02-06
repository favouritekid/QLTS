#!/usr/bin/env python3
"""
Check which users have leads assigned.
Run: python scripts/check_user_leads.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "development")


async def main():
    from sqlalchemy import select, func
    from app.database import AsyncSessionLocal
    from app.models import User, Lead

    print("\n" + "=" * 80)
    print("🔍 CHECK: Users and their assigned leads")
    print("=" * 80)

    async with AsyncSessionLocal() as db:
        # Find all users with their lead counts
        query = (
            select(
                User.id,
                User.username,
                User.full_name,
                User.role,
                func.count(Lead.id).label("lead_count")
            )
            .outerjoin(Lead, (Lead.assigned_officer_id == User.id) & (Lead.deleted_at.is_(None)))
            .group_by(User.id, User.username, User.full_name, User.role)
            .order_by(func.count(Lead.id).desc())
        )
        result = await db.execute(query)
        users = result.fetchall()

        print(f"\n{'ID':<6} {'Username':<20} {'Full Name':<25} {'Role':<12} {'Leads':<8}")
        print("-" * 80)

        total_leads_assigned = 0
        users_with_leads = 0

        for user in users:
            print(f"{user.id:<6} {user.username:<20} {(user.full_name or 'N/A')[:24]:<25} {user.role:<12} {user.lead_count:<8}")
            total_leads_assigned += user.lead_count
            if user.lead_count > 0:
                users_with_leads += 1

        print("-" * 90)
        print(f"Total users: {len(users)}")
        print(f"Users with leads: {users_with_leads}")
        print(f"Total assigned leads: {total_leads_assigned}")

        # Check for user "Phạm Thái Hà"
        print("\n" + "=" * 80)
        print("🔍 Looking for user 'Phạm Thái Hà'...")

        pha_user = next((u for u in users if u.full_name and "Thái Hà" in u.full_name), None)
        if pha_user:
            print(f"  Found: ID={pha_user.id}, Username={pha_user.username}")
            print(f"  Role: {pha_user.role}")
            print(f"  Leads assigned: {pha_user.lead_count}")

            if pha_user.role in ["admin", "manager"]:
                print(f"\n  💡 As {pha_user.role}, this user should use:")
                print(f"     - 'Tổ chức' scope to see ALL leads (organization view)")
                print(f"     - 'Đội' scope to see team leads")
        else:
            print("  User not found!")

        # Check total leads in system
        total_query = select(func.count(Lead.id)).where(Lead.deleted_at.is_(None))
        total_result = await db.execute(total_query)
        total_in_system = total_result.scalar()

        unassigned = total_in_system - total_leads_assigned

        print(f"\n📊 Lead Distribution:")
        print(f"  Total leads in system: {total_in_system}")
        print(f"  Assigned to officers: {total_leads_assigned}")
        print(f"  Unassigned: {unassigned}")

        print("\n" + "=" * 80 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
