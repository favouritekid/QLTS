# tests/fixtures/__init__.py
"""
Track T: Modular test fixtures.

Modules:
- database.py: Schema init, truncation, safety checks
- redis.py: FakeRedis patching (must be called before app import)
- users.py: User creation + token helpers
- builders.py: Seed data builders (SeedDependenciesBuilder)
- constants.py: Test data constants (URLs, user defs, org data)
"""
