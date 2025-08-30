import os
import uuid
from datetime import datetime, timedelta

from fastapi import FastAPI, Request
import asyncpg

app = FastAPI()

# Neon Database
DATABASE_URL = os.getenv("DATABASE_URL")

async def get_conn():
    return await asyncpg.connect(DATABASE_URL)

SESSION_TTL = timedelta(minutes=6)

def generate_code() -> str:
    return uuid.uuid4().hex[:6].upper()

@app.post("/session/create")
async def create_session(req: Request):
    data = await req.json()
    ip = data["host_ip"]

    code = generate_code()
    now = datetime.now()
    expires = now + SESSION_TTL

    conn = await get_conn()
    try:
        await conn.execute("""INSERT INTO sessions (code, ip, created_at, updated_at, expires_at)
                              VALUES ($1, $2, $3, $3, $4)""",
                           code,
                           ip,
                           now,
                           expires)
    finally:
        await conn.close()

    return {"status": "ok", "code": code, "expires": expires}

@app.post("/session/keepalive")
async def keepalive_session(req: Request):
    data = await req.json()
    code = data["code"]
    now = datetime.now()
    expires = now + SESSION_TTL

    conn = await get_conn()
    try:
        result = await conn.execute(
            """
            UPDATE sessions
            SET updated_at = $2,
                expires_at = $3
            WHERE code = $1
              AND expires_at < $2""",
            code,
            now,
            expires
        )
    finally:
        await conn.close()

    if result == "UPDATE 0":
        return {"status": "error", "code": code, "message": "Session not found or expired"}

    return {"status": "ok", "code": code, "expires": expires}

@app.post("/session/close")
async def close_session(req: Request):
    data = await req.json()
    code = data["code"]

    conn = await get_conn()
    try:
        result = await conn.execute("DELETE FROM sessions WHERE code = $1", code)
    finally:
        await conn.close()

    if result == "DELETE 0":
        return {"status": "error", "code": code, "message": "Session not found"}

    return {"status": "ok"}

@app.post("/session/join")
async def join_session(req: Request):
    data = await req.json()
    code = data["code"]
    now = datetime.now()

    conn = await get_conn()
    try:
        row = await conn.fetchrow("SELECT * FROM sessions WHERE code = $1 AND expires_at > $2", code, now)
    finally:
        await conn.close()

    if not row:
        return {"status": "error", "code": code, "message": "Session not found or expired"}

    return {"status": "ok", "code": code, "ip": row["ip"]}

@app.get("/session/list")
async def list_sessions():
    conn = await get_conn()
    try:
        rows = await conn.fetch(
            """
            SELECT code, ip, created_at, updated_at, expires_at
            FROM sessions
            ORDER BY created_at"""
        )
    finally:
        await conn.close()

    active = []
    expired = []
    for r in rows:
        line = f"[{r["code"]}] <{r["ip"]:16}> | {r["created_at"]:15} | {r["updated_at"]:15} | {r["expires_at"]:15} | "
        if r["expires_at"] < datetime.now():
            expired.append(line)
        else:
            active.append(line)

    output = []
    output.append("=== ACTIVE  ===")
    output.append(f"[ CODE ] <       IP       > | {"CREATED":15} | {"UPDATED":15} | {"EXPIRES":15} | ")
    output.extend(active)

    output.append("=== EXPIRED ===")
    output.append(f"[ CODE ] <       IP       > | {"CREATED":15} | {"UPDATED":15} | {"EXPIRES":15} | ")
    output.extend(expired)

    return "\n".join(output)