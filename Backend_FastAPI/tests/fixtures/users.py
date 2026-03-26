# tests/fixtures/users.py
"""
Track T: Centralized user creation and token helpers.

Replaces 4 duplicated user fixture sets across conftest files.
Standard return: dict with id, username, email, password.
"""
import logging
from typing import Optional

from sqlalchemy import insert

log = logging.getLogger(__name__)


async def create_user_with_role(
    session_factory,
    user_data: dict,
    casbin_role: str,
    unit_id: Optional[int] = None,
    models=None,
    get_password_hash=None,
    CasbinRule=None,
    app=None,
) -> dict:
    """
    Create a user in DB and assign Casbin role.

    Args:
        session_factory: AsyncSessionLocal factory
        user_data: dict with username, email, password, role, status
        casbin_role: e.g. "role:admin", "role:officer"
        unit_id: optional organization unit ID
        models: app.models module
        get_password_hash: password hashing function
        CasbinRule: Casbin rule model (optional)
        app: FastAPI app instance for Casbin policy reload

    Returns:
        dict with id, username, email, password
    """
    user_info = {}
    async with session_factory() as session:
        async with session.begin():
            user = models.User(
                username=user_data["username"],
                email=user_data["email"],
                password_hash=get_password_hash(user_data["password"]),
                role=user_data["role"],
                status=user_data["status"],
                unit_id=unit_id,
            )
            session.add(user)
            await session.flush()
            db_user_id = user.id
            if not db_user_id:
                raise Exception(
                    f"Failed to get auto-generated ID for user {user_data['username']}"
                )

            if CasbinRule:
                casbin_policy = insert(CasbinRule).values(
                    ptype="g", v0=f"user:{db_user_id}", v1=casbin_role
                )
                await session.execute(casbin_policy)

            user_info = {
                "id": db_user_id,
                "username": user_data["username"],
                "email": user_data["email"],
                "password": user_data["password"],
            }

    # Reload Casbin policies
    if app and hasattr(app.state, "enforcer") and app.state.enforcer:
        try:
            await app.state.enforcer.load_policy()
            log.info(f"Casbin policies reloaded after creating user {user_data['username']}")
        except Exception as e:
            log.error(f"Failed to reload Casbin policies: {e}")

    return user_info


async def get_auth_headers(client, user_info: dict, login_url: str) -> dict:
    """
    Login and return auth headers.

    Extracts access_token from httpOnly cookie, returns as Authorization header
    for backward compatibility.

    Args:
        client: httpx AsyncClient
        user_info: dict with username, password
        login_url: login endpoint URL

    Returns:
        dict {"Authorization": "Bearer <token>"}
    """
    import pytest

    login_data = {"username": user_info["username"], "password": user_info["password"]}
    res = await client.post(login_url, data=login_data)
    if res.status_code != 200:
        pytest.fail(
            f"{user_info['username']} login failed: Status {res.status_code} - {res.text}"
        )

    access_token = res.cookies.get("access_token")
    if not access_token:
        pytest.fail(
            f"{user_info['username']} login succeeded but access_token cookie not found"
        )

    return {"Authorization": f"Bearer {access_token}"}
