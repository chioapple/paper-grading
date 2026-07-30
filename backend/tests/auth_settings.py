"""测试使用的显式 Supabase 配置。"""

import base64
from typing import TypedDict


class TestAuthSettings(TypedDict):
    REDIS_URL: str
    SUPABASE_URL: str
    SUPABASE_PUBLISHABLE_KEY: str
    SUPABASE_SECRET_KEY: str
    AUTH_INVITE_REDIRECT_URL: str
    FRONTEND_ORIGIN: str
    PROVIDER_MASTER_KEY: str
    SUPABASE_STORAGE_BUCKET: str


TEST_AUTH_SETTINGS: TestAuthSettings = {
    "REDIS_URL": "redis://127.0.0.1:6379/0",
    "SUPABASE_URL": "https://test-project.supabase.co",
    "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test",
    "SUPABASE_SECRET_KEY": "sb_secret_test",  # pragma: allowlist secret
    "AUTH_INVITE_REDIRECT_URL": "http://127.0.0.1:5173/auth/callback",
    "FRONTEND_ORIGIN": "http://127.0.0.1:5173",
    "PROVIDER_MASTER_KEY": base64.b64encode(bytes(range(32))).decode("ascii"),
    "SUPABASE_STORAGE_BUCKET": "paper-grading-test",
}
