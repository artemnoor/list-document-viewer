"""Small shared-workspace accounts: email/password, no email or phone verification."""
import hashlib
import secrets
import uuid
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from psycopg.errors import UniqueViolation

COOKIE = "trace_session"
SESSION_SECONDS = 30 * 24 * 60 * 60


class Credentials(BaseModel):
    email: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=1024)


def password_hash(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f"{salt}:{digest}"


def password_matches(password: str, stored: str) -> bool:
    try:
        salt, _ = stored.split(":", 1)
        return secrets.compare_digest(password_hash(password, salt), stored)
    except (ValueError, TypeError):
        return False


def session_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def ensure_accounts(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS trace_users (
        id text PRIMARY KEY, email text NOT NULL UNIQUE, password_hash text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now()
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS trace_sessions (
        token_hash text PRIMARY KEY, user_id text NOT NULL REFERENCES trace_users(id) ON DELETE CASCADE,
        expires_at timestamptz NOT NULL
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS trace_sessions_expiry_idx ON trace_sessions(expires_at)")


def check_origin(request: Request):
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc.lower() != request.headers.get("host", "").lower():
        raise HTTPException(403, "Откройте форму на сайте Phystech Trace")


def public_user(user):
    return {"id": user["id"], "email": user["email"], "name": user["email"].split("@")[0]}


def create_auth_router(database):
    router = APIRouter(prefix="/api/auth", tags=["Accounts"])

    def issue_session(conn, user, request, response):
        token = secrets.token_urlsafe(32)
        previous = request.cookies.get(COOKIE)
        if previous:
            conn.execute("DELETE FROM trace_sessions WHERE token_hash=%s", (session_digest(previous),))
        conn.execute("DELETE FROM trace_sessions WHERE expires_at <= now()")
        conn.execute("INSERT INTO trace_sessions(token_hash,user_id,expires_at) VALUES(%s,%s,now()+interval '30 days')",
                     (session_digest(token), user["id"]))
        response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True,
                            secure=request.url.scheme == "https", samesite="lax", path="/")
        response.headers["Cache-Control"] = "no-store"

    @router.post("/register", status_code=201)
    def register(payload: Credentials, request: Request, response: Response):
        check_origin(request)
        email = payload.email.strip().casefold()
        if not email:
            raise HTTPException(422, "Укажите почту")
        user = {"id": str(uuid.uuid4()), "email": email}
        hashed = password_hash(payload.password)
        try:
            with database() as conn:
                conn.execute("INSERT INTO trace_users(id,email,password_hash) VALUES(%s,%s,%s)",
                             (user["id"], email, hashed))
                issue_session(conn, user, request, response)
                conn.commit()
        except UniqueViolation:
            raise HTTPException(409, "Эта почта уже зарегистрирована. Войдите в аккаунт.")
        return {"user": public_user(user)}

    @router.post("/login")
    def login(payload: Credentials, request: Request, response: Response):
        check_origin(request)
        with database() as conn:
            user = conn.execute("SELECT * FROM trace_users WHERE email=%s", (payload.email.strip().casefold(),)).fetchone()
            if not user or not password_matches(payload.password, user["password_hash"]):
                raise HTTPException(401, "Проверьте почту и пароль")
            issue_session(conn, user, request, response)
            conn.commit()
        return {"user": public_user(user)}

    @router.get("/me")
    def current_user(request: Request, response: Response):
        response.headers["Cache-Control"] = "no-store"
        token = request.cookies.get(COOKIE)
        if not token:
            raise HTTPException(401, "Войдите в аккаунт")
        with database() as conn:
            user = conn.execute("""SELECT u.id,u.email FROM trace_sessions s
                JOIN trace_users u ON u.id=s.user_id WHERE s.token_hash=%s AND s.expires_at>now()""",
                                (session_digest(token),)).fetchone()
        if not user:
            raise HTTPException(401, "Войдите в аккаунт")
        return {"user": public_user(user)}

    @router.post("/logout", status_code=204)
    def logout(request: Request, response: Response):
        check_origin(request)
        token = request.cookies.get(COOKIE)
        if token:
            with database() as conn:
                conn.execute("DELETE FROM trace_sessions WHERE token_hash=%s", (session_digest(token),))
                conn.commit()
        response.delete_cookie(COOKIE, path="/")
        response.headers["Cache-Control"] = "no-store"

    return router
