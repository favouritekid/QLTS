#!/usr/bin/env python3
"""
Script tạo test users cho Diamond Inheritance testing.

Chạy:
    cd /mnt/d/QLTS/Backend_FastAPI
    source venv/bin/activate
    python scripts/create_test_users.py

Script sẽ tạo các users:
- test_officer@example.com (role: officer)
- test_accountant@example.com (role: accountant)
- test_manager@example.com (role: manager)
- test_admin@example.com (role: admin)

Password cho tất cả: Test@123456
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, engine
from app.models.user import User
from app.security import get_password_hash


# Test users configuration
TEST_USERS = [
    {
        "email": "test_officer@example.com",
        "full_name": "Test Officer",
        "role": "officer",
        "casbin_role": "role:officer",
    },
    {
        "email": "test_accountant@example.com",
        "full_name": "Test Accountant (Kế toán)",
        "role": "accountant",
        "casbin_role": "role:accountant",
    },
    {
        "email": "test_manager@example.com",
        "full_name": "Test Manager",
        "role": "manager",
        "casbin_role": "role:manager",
    },
    {
        "email": "test_admin@example.com",
        "full_name": "Test Admin",
        "role": "admin",
        "casbin_role": "role:admin",
    },
]

DEFAULT_PASSWORD = "Test@123456"


async def create_test_users():
    """Create test users and assign Casbin roles."""

    print("=" * 60)
    print("🔧 Creating Test Users for Diamond Inheritance Testing")
    print("=" * 60)

    async with AsyncSessionLocal() as session:
        # Get default unit_id (first unit)
        result = await session.execute(text(
            "SELECT id FROM organization_unit LIMIT 1"
        ))
        row = result.fetchone()
        default_unit_id = row[0] if row else None

        if not default_unit_id:
            print("❌ No organization unit found. Please create one first.")
            return

        print(f"📍 Using unit_id: {default_unit_id}")
        print(f"🔑 Default password: {DEFAULT_PASSWORD}")
        print("-" * 60)

        hashed_password = get_password_hash(DEFAULT_PASSWORD)

        for user_config in TEST_USERS:
            email = user_config["email"]

            # Check if user already exists
            result = await session.execute(
                select(User).where(User.email == email)
            )
            existing_user = result.scalar_one_or_none()

            if existing_user:
                print(f"⏭️  User {email} already exists (id={existing_user.id})")
                user_id = existing_user.id

                # Update role if different
                if existing_user.role != user_config["role"]:
                    existing_user.role = user_config["role"]
                    await session.flush()
                    print(f"   → Updated role to: {user_config['role']}")
            else:
                # Create new user
                # Generate username from email (before @)
                username = email.split("@")[0]

                new_user = User(
                    username=username,
                    email=email,
                    full_name=user_config["full_name"],
                    password_hash=hashed_password,
                    role=user_config["role"],
                    unit_id=default_unit_id,
                    status="active",
                )
                session.add(new_user)
                await session.flush()
                user_id = new_user.id
                print(f"✅ Created user: {email} (id={user_id})")

            # Add Casbin grouping policy (user -> role)
            casbin_role = user_config["casbin_role"]
            user_subject = f"user:{user_id}"

            # Check if grouping policy exists
            result = await session.execute(text(f"""
                SELECT 1 FROM casbin_rule
                WHERE ptype = 'g' AND v0 = '{user_subject}' AND v1 = '{casbin_role}'
            """))

            if not result.fetchone():
                await session.execute(text(f"""
                    INSERT INTO casbin_rule (ptype, v0, v1, template_id, applied_at)
                    VALUES ('g', '{user_subject}', '{casbin_role}', '_manual', NOW())
                """))
                print(f"   → Assigned Casbin role: {casbin_role}")
            else:
                print(f"   → Casbin role already assigned: {casbin_role}")

        await session.commit()

        print("-" * 60)
        print("✅ All test users created/updated successfully!")
        print()
        print("📋 LOGIN CREDENTIALS:")
        print("-" * 60)
        for user_config in TEST_USERS:
            print(f"   Email: {user_config['email']}")
            print(f"   Password: {DEFAULT_PASSWORD}")
            print(f"   Role: {user_config['role']}")
            print()


async def show_user_permissions():
    """Show current users and their Casbin permissions."""

    print("=" * 60)
    print("📊 Current Users and Casbin Roles")
    print("=" * 60)

    async with AsyncSessionLocal() as session:
        # Get all test users
        for user_config in TEST_USERS:
            result = await session.execute(
                select(User).where(User.email == user_config["email"])
            )
            user = result.scalar_one_or_none()

            if user:
                print(f"\n👤 {user.email} (id={user.id})")
                print(f"   DB Role: {user.role}")

                # Get Casbin roles
                result = await session.execute(text(f"""
                    SELECT v1 FROM casbin_rule
                    WHERE ptype = 'g' AND v0 = 'user:{user.id}'
                """))
                casbin_roles = [r[0] for r in result.fetchall()]
                print(f"   Casbin Roles: {casbin_roles}")

                # Get inherited roles (via g-rules)
                for role in casbin_roles:
                    result = await session.execute(text(f"""
                        WITH RECURSIVE role_hierarchy AS (
                            SELECT v0 as child, v1 as parent
                            FROM casbin_rule
                            WHERE ptype = 'g' AND v0 = '{role}'

                            UNION ALL

                            SELECT cr.v0, cr.v1
                            FROM casbin_rule cr
                            JOIN role_hierarchy rh ON cr.v0 = rh.parent
                            WHERE cr.ptype = 'g' AND cr.v0 LIKE 'role:%'
                        )
                        SELECT parent FROM role_hierarchy
                    """))
                    inherited = [r[0] for r in result.fetchall()]
                    if inherited:
                        print(f"   Inherited: {inherited}")


async def test_diamond_permissions():
    """Test that diamond inheritance works correctly."""

    print("=" * 60)
    print("🧪 Testing Diamond Inheritance Permissions")
    print("=" * 60)

    async with AsyncSessionLocal() as session:
        # Get accountant-specific policies
        result = await session.execute(text("""
            SELECT v1, v2 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:accountant'
            AND v1 LIKE '/api/payments%'
        """))
        accountant_payment_policies = result.fetchall()

        print("\n📝 Accountant Payment Policies:")
        for obj, action in accountant_payment_policies:
            print(f"   {action} {obj}")

        # Get manager policies - should NOT have payment record/verify
        result = await session.execute(text("""
            SELECT v1, v2 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:manager'
            AND v1 LIKE '/api/payments%'
        """))
        manager_payment_policies = result.fetchall()

        print("\n📝 Manager Payment Policies:")
        if manager_payment_policies:
            for obj, action in manager_payment_policies:
                print(f"   {action} {obj}")
        else:
            print("   (none - correct! separation of duties)")

        # Check admin inherits both
        result = await session.execute(text("""
            SELECT v1 FROM casbin_rule
            WHERE ptype = 'g' AND v0 = 'role:admin'
        """))
        admin_parents = [r[0] for r in result.fetchall()]

        print("\n📝 Admin Inheritance:")
        print(f"   Inherits from: {admin_parents}")

        if 'role:manager' in admin_parents and 'role:accountant' in admin_parents:
            print("   ✅ Diamond Inheritance CORRECT!")
        else:
            print("   ❌ Diamond Inheritance MISSING!")


async def main():
    """Main function."""
    import argparse

    parser = argparse.ArgumentParser(description="Create test users for Diamond Inheritance testing")
    parser.add_argument("--create", action="store_true", help="Create test users")
    parser.add_argument("--show", action="store_true", help="Show current users and permissions")
    parser.add_argument("--test", action="store_true", help="Test diamond inheritance")
    parser.add_argument("--all", action="store_true", help="Run all operations")

    args = parser.parse_args()

    if args.all or (not args.create and not args.show and not args.test):
        await create_test_users()
        print()
        await show_user_permissions()
        print()
        await test_diamond_permissions()
    else:
        if args.create:
            await create_test_users()
        if args.show:
            await show_user_permissions()
        if args.test:
            await test_diamond_permissions()


if __name__ == "__main__":
    asyncio.run(main())
