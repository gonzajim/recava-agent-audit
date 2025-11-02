"""Firebase authentication helpers for FastAPI dependencies."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

import firebase_admin
from fastapi import Header, HTTPException
from firebase_admin import auth as fb_auth, credentials

logger = logging.getLogger(__name__)

if not firebase_admin._apps:
    project_id = os.getenv("FIREBASE_PROJECT_ID") or os.getenv("GCLOUD_PROJECT")
    initialize_kwargs: Dict[str, Any] = {}
    options: Dict[str, Any] = {}
    if project_id:
        options["projectId"] = project_id

    if os.getenv("FIREBASE_AUTH_EMULATOR_HOST"):
        if options:
            initialize_kwargs["options"] = options
        firebase_admin.initialize_app(**initialize_kwargs)
    else:
        cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if cred_path and os.path.exists(cred_path):
            initialize_kwargs["credential"] = credentials.Certificate(cred_path)
        if options:
            initialize_kwargs["options"] = options
        firebase_admin.initialize_app(**initialize_kwargs)

    logger.info(
        "Firebase Admin SDK initialized for advisor backend (project=%s, emulator=%s).",
        options.get("projectId", "auto"),
        bool(os.getenv("FIREBASE_AUTH_EMULATOR_HOST")),
    )


ADMIN_WHITELIST = {
    "gonzalo.jimenez.martin@gmail.com",
}


async def require_firebase_user(authorization: str = Header(default=None)) -> Dict[str, Any]:
    """Validate Firebase ID token and ensure email is verified."""
    if not authorization or not authorization.startswith("Bearer "):
        logger.debug("Authorization header missing or invalid.")
        raise HTTPException(status_code=401, detail="Falta Authorization Bearer token")

    id_token = authorization.split(" ", 1)[1]
    try:
        decoded = fb_auth.verify_id_token(id_token)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Firebase token verification failed: %s", exc)
        raise HTTPException(status_code=401, detail="Token inválido") from exc

    if not decoded.get("email_verified", False):
        raise HTTPException(status_code=403, detail="Email no verificado")

    return decoded


async def require_admin_user(authorization: str = Header(default=None)) -> Dict[str, Any]:
    """Ensure the caller is an authenticated admin user."""
    decoded = await require_firebase_user(authorization)

    allowed_emails = {
        email.strip().lower()
        for email in os.getenv("ADMIN_ALLOWED_EMAILS", "").split(",")
        if email.strip()
    }
    allowed_emails.update(ADMIN_WHITELIST)
    email = (decoded.get("email") or "").lower()

    is_admin_claim = any(
        bool(decoded.get(key))
        for key in ("admin", "is_admin", "role_admin")
    ) or decoded.get("role") == "admin"

    if allowed_emails and email not in allowed_emails:
        raise HTTPException(status_code=403, detail="Usuario no autorizado para administrar configuraciones.")

    if not is_admin_claim and not allowed_emails:
        raise HTTPException(status_code=403, detail="Permisos de administrador requeridos.")

    return decoded
