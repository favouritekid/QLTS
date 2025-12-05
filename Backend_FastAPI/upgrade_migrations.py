#!/usr/bin/env python3
"""
Script to upgrade Alembic migrations to all heads.
This merges multiple migration branches.
"""
import asyncio
from alembic.config import Config
from alembic import command

def main():
    """Run Alembic upgrade to heads."""
    # Create Alembic config
    alembic_cfg = Config("alembic.ini")

    # Upgrade to all heads (merges branches)
    print("Upgrading database to all migration heads...")
    command.upgrade(alembic_cfg, "heads")
    print("✅ Migration upgrade completed successfully!")

if __name__ == "__main__":
    main()
