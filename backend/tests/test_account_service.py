"""账户管理用例测试。"""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.auth.models import ProfileRecord
from app.auth.service import AccountService, AccountStateError, AccountSyncError
from app.auth.supabase import AuthUser


@pytest.mark.anyio
async def test_list_teachers_ignores_auth_users_without_a_teacher_profile() -> None:
    auth_users = [
        AuthUser(
            id=UUID("11111111-1111-1111-1111-111111111111"),
            email="admin@example.edu",
            invited_at=None,
            created_at=datetime(2026, 7, 1, tzinfo=UTC),
            last_sign_in_at=datetime(2026, 7, 1, tzinfo=UTC),
            banned_until=None,
        ),
        AuthUser(
            id=UUID("22222222-2222-2222-2222-222222222222"),
            email="teacher@example.edu",
            invited_at=datetime(2026, 7, 13, tzinfo=UTC),
            created_at=datetime(2026, 7, 13, tzinfo=UTC),
            last_sign_in_at=None,
            banned_until=None,
        ),
        AuthUser(
            id=UUID("33333333-3333-3333-3333-333333333333"),
            email="uninvited@example.edu",
            invited_at=None,
            created_at=datetime(2026, 7, 13, tzinfo=UTC),
            last_sign_in_at=None,
            banned_until=None,
        ),
    ]

    class StubGateway:
        async def list_users(self, *, page: int, per_page: int) -> list[AuthUser]:
            assert per_page == 1000
            return auth_users if page == 1 else []

    class StubProfiles:
        async def list_by_ids(self, user_ids: set[UUID]) -> list[ProfileRecord]:
            assert user_ids == {user.id for user in auth_users}
            return [
                ProfileRecord(
                    id=auth_users[0].id,
                    display_name="总管理员",
                    role="admin",
                    status="active",
                ),
                ProfileRecord(
                    id=auth_users[1].id,
                    display_name="张老师",
                    role="teacher",
                    status="invited",
                ),
            ]

    service = AccountService(gateway=StubGateway(), profiles=StubProfiles())  # type: ignore[arg-type]

    teachers = await service.list_teachers()

    assert [teacher.model_dump() for teacher in teachers] == [
        {
            "id": UUID("22222222-2222-2222-2222-222222222222"),
            "email": "teacher@example.edu",
            "display_name": "张老师",
            "status": "invited",
            "invited_at": datetime(2026, 7, 13, tzinfo=UTC),
        }
    ]


@pytest.mark.anyio
async def test_invite_teacher_requires_the_database_triggered_profile() -> None:
    invited_user = AuthUser(
        id=UUID("22222222-2222-2222-2222-222222222222"),
        email="teacher@example.edu",
        invited_at=datetime(2026, 7, 13, tzinfo=UTC),
        created_at=datetime(2026, 7, 13, tzinfo=UTC),
        last_sign_in_at=None,
        banned_until=None,
    )

    class StubGateway:
        async def list_users(self, *, page: int, per_page: int) -> list[AuthUser]:
            return []

        async def invite_teacher(self, *, email: str, display_name: str) -> AuthUser:
            assert (email, display_name) == ("teacher@example.edu", "张老师")
            return invited_user

    class StubProfiles:
        async def get_by_id(self, user_id: UUID) -> ProfileRecord | None:
            assert user_id == invited_user.id
            return ProfileRecord(
                id=user_id,
                display_name="张老师",
                role="teacher",
                status="invited",
            )

    service = AccountService(gateway=StubGateway(), profiles=StubProfiles())  # type: ignore[arg-type]

    teacher = await service.invite_teacher(
        email="teacher@example.edu",
        display_name="张老师",
    )

    assert teacher.status == "invited"
    assert teacher.email == "teacher@example.edu"


@pytest.mark.anyio
async def test_invite_teacher_rejects_an_existing_auth_email() -> None:
    existing_user = AuthUser(
        id=UUID("22222222-2222-2222-2222-222222222222"),
        email="teacher@example.edu",
        invited_at=datetime(2026, 7, 13, tzinfo=UTC),
        created_at=datetime(2026, 7, 13, tzinfo=UTC),
        last_sign_in_at=None,
        banned_until=None,
    )

    class StubGateway:
        async def list_users(self, *, page: int, per_page: int) -> list[AuthUser]:
            return [existing_user] if page == 1 else []

        async def invite_teacher(self, *, email: str, display_name: str) -> AuthUser:
            raise AssertionError("已有邮箱不应再次发送邀请")

    class StubProfiles:
        pass

    service = AccountService(gateway=StubGateway(), profiles=StubProfiles())  # type: ignore[arg-type]

    with pytest.raises(AccountStateError, match="邮箱已经存在"):
        await service.invite_teacher(
            email="teacher@example.edu",
            display_name="张老师",
        )


@pytest.mark.anyio
async def test_complete_invite_activates_only_the_invited_profile() -> None:
    user_id = UUID("22222222-2222-2222-2222-222222222222")

    class StubGateway:
        pass

    class StubProfiles:
        def __init__(self) -> None:
            self.profile = ProfileRecord(
                id=user_id,
                display_name="张老师",
                role="teacher",
                status="invited",
            )

        async def get_by_id(self, requested_id: UUID) -> ProfileRecord | None:
            assert requested_id == user_id
            return self.profile

        async def activate_invited(self, requested_id: UUID) -> bool:
            assert requested_id == user_id
            self.profile = self.profile.model_copy(update={"status": "active"})
            return True

    profiles = StubProfiles()
    service = AccountService(gateway=StubGateway(), profiles=profiles)  # type: ignore[arg-type]

    profile = await service.complete_invite(user_id)

    assert profile.status == "active"


@pytest.mark.anyio
async def test_complete_invite_is_idempotent_for_the_bootstrapped_admin() -> None:
    user_id = UUID("11111111-1111-1111-1111-111111111111")
    admin = ProfileRecord(
        id=user_id,
        display_name="总管理员",
        role="admin",
        status="active",
    )

    class StubGateway:
        pass

    class StubProfiles:
        async def get_by_id(self, requested_id: UUID) -> ProfileRecord | None:
            assert requested_id == user_id
            return admin

    service = AccountService(gateway=StubGateway(), profiles=StubProfiles())  # type: ignore[arg-type]

    profile = await service.complete_invite(user_id)

    assert profile == admin


@pytest.mark.anyio
async def test_disable_teacher_commits_profile_before_banning_auth_user() -> None:
    user_id = UUID("22222222-2222-2222-2222-222222222222")
    events: list[str] = []

    class StubGateway:
        async def disable_user(self, requested_id: UUID) -> AuthUser:
            assert requested_id == user_id
            events.append("auth_disabled")
            return AuthUser(
                id=user_id,
                email="teacher@example.edu",
                invited_at=None,
                created_at=datetime(2026, 7, 1, tzinfo=UTC),
                last_sign_in_at=datetime(2026, 7, 2, tzinfo=UTC),
                banned_until=datetime(2126, 7, 1, tzinfo=UTC),
            )

    class StubProfiles:
        def __init__(self) -> None:
            self.status = "active"

        async def get_by_id(self, requested_id: UUID) -> ProfileRecord | None:
            return ProfileRecord(
                id=requested_id,
                display_name="张老师",
                role="teacher",
                status=self.status,
            )

        async def disable_active(self, requested_id: UUID) -> bool:
            assert requested_id == user_id
            self.status = "disabled"
            events.append("profile_disabled")
            return True

    service = AccountService(gateway=StubGateway(), profiles=StubProfiles())  # type: ignore[arg-type]

    profile = await service.disable_teacher(user_id)

    assert profile.status == "disabled"
    assert events == ["profile_disabled", "auth_disabled"]


@pytest.mark.anyio
async def test_enable_teacher_unbans_auth_before_opening_application_access() -> None:
    user_id = UUID("22222222-2222-2222-2222-222222222222")
    events: list[str] = []

    class StubGateway:
        async def enable_user(self, requested_id: UUID) -> AuthUser:
            assert requested_id == user_id
            events.append("auth_enabled")
            return AuthUser(
                id=user_id,
                email="teacher@example.edu",
                invited_at=None,
                created_at=datetime(2026, 7, 1, tzinfo=UTC),
                last_sign_in_at=datetime(2026, 7, 2, tzinfo=UTC),
                banned_until=None,
            )

    class StubProfiles:
        def __init__(self) -> None:
            self.status = "disabled"

        async def get_by_id(self, requested_id: UUID) -> ProfileRecord | None:
            return ProfileRecord(
                id=requested_id,
                display_name="张老师",
                role="teacher",
                status=self.status,
            )

        async def enable_disabled(self, requested_id: UUID) -> bool:
            assert requested_id == user_id
            self.status = "active"
            events.append("profile_enabled")
            return True

    service = AccountService(gateway=StubGateway(), profiles=StubProfiles())  # type: ignore[arg-type]

    profile = await service.enable_teacher(user_id)

    assert profile.status == "active"
    assert events == ["auth_enabled", "profile_enabled"]


@pytest.mark.anyio
async def test_enable_teacher_keeps_application_access_closed_when_auth_remains_banned() -> None:
    user_id = UUID("22222222-2222-2222-2222-222222222222")

    class StubGateway:
        async def enable_user(self, requested_id: UUID) -> AuthUser:
            assert requested_id == user_id
            return AuthUser(
                id=user_id,
                email="teacher@example.edu",
                invited_at=None,
                created_at=datetime(2026, 7, 1, tzinfo=UTC),
                last_sign_in_at=datetime(2026, 7, 2, tzinfo=UTC),
                banned_until=datetime(2126, 7, 1, tzinfo=UTC),
            )

    class StubProfiles:
        async def get_by_id(self, requested_id: UUID) -> ProfileRecord | None:
            return ProfileRecord(
                id=requested_id,
                display_name="张老师",
                role="teacher",
                status="disabled",
            )

        async def enable_disabled(self, requested_id: UUID) -> bool:
            raise AssertionError("Auth 仍封禁时不得开放应用权限")

    service = AccountService(gateway=StubGateway(), profiles=StubProfiles())  # type: ignore[arg-type]

    with pytest.raises(AccountSyncError, match="未确认解除封禁"):
        await service.enable_teacher(user_id)


@pytest.mark.anyio
async def test_disable_teacher_retry_repairs_a_previous_auth_failure() -> None:
    user_id = UUID("22222222-2222-2222-2222-222222222222")

    class StubGateway:
        async def disable_user(self, requested_id: UUID) -> AuthUser:
            assert requested_id == user_id
            return AuthUser(
                id=user_id,
                email="teacher@example.edu",
                invited_at=None,
                created_at=datetime(2026, 7, 1, tzinfo=UTC),
                last_sign_in_at=datetime(2026, 7, 2, tzinfo=UTC),
                banned_until=datetime(2126, 7, 1, tzinfo=UTC),
            )

    class StubProfiles:
        async def get_by_id(self, requested_id: UUID) -> ProfileRecord | None:
            return ProfileRecord(
                id=requested_id,
                display_name="张老师",
                role="teacher",
                status="disabled",
            )

        async def disable_active(self, requested_id: UUID) -> bool:
            raise AssertionError("重试时不应再次修改已停用的 profile")

    service = AccountService(gateway=StubGateway(), profiles=StubProfiles())  # type: ignore[arg-type]

    profile = await service.disable_teacher(user_id)

    assert profile.status == "disabled"


@pytest.mark.anyio
async def test_bootstrap_admin_promotes_one_existing_invited_user() -> None:
    user_id = UUID("11111111-1111-1111-1111-111111111111")
    auth_user = AuthUser(
        id=user_id,
        email="admin@example.edu",
        invited_at=datetime(2026, 7, 14, tzinfo=UTC),
        created_at=datetime(2026, 7, 14, tzinfo=UTC),
        last_sign_in_at=None,
        banned_until=None,
    )

    class StubGateway:
        async def list_users(self, *, page: int, per_page: int) -> list[AuthUser]:
            assert per_page == 1000
            return [auth_user] if page == 1 else []

    class StubProfiles:
        def __init__(self) -> None:
            self.profile = ProfileRecord(
                id=user_id,
                display_name="总管理员",
                role="teacher",
                status="invited",
            )

        async def get_admin(self) -> ProfileRecord | None:
            return None

        async def get_by_id(self, requested_id: UUID) -> ProfileRecord | None:
            assert requested_id == user_id
            return self.profile

        async def promote_invited_to_admin(
            self,
            requested_id: UUID,
            display_name: str,
        ) -> bool:
            assert (requested_id, display_name) == (user_id, "总管理员")
            self.profile = self.profile.model_copy(update={"role": "admin", "status": "active"})
            return True

    service = AccountService(gateway=StubGateway(), profiles=StubProfiles())  # type: ignore[arg-type]

    account = await service.bootstrap_admin(
        email="admin@example.edu",
        display_name="总管理员",
    )

    assert account.role == "admin"
    assert account.status == "active"


@pytest.mark.anyio
async def test_bootstrap_admin_rejects_a_consumed_invitation() -> None:
    user_id = UUID("11111111-1111-1111-1111-111111111111")
    auth_user = AuthUser(
        id=user_id,
        email="admin@example.edu",
        invited_at=datetime(2026, 7, 14, tzinfo=UTC),
        created_at=datetime(2026, 7, 14, tzinfo=UTC),
        last_sign_in_at=datetime(2026, 7, 14, tzinfo=UTC),
        banned_until=None,
    )

    class StubGateway:
        async def list_users(self, *, page: int, per_page: int) -> list[AuthUser]:
            return [auth_user] if page == 1 else []

    class StubProfiles:
        async def get_admin(self) -> ProfileRecord | None:
            return None

        async def get_by_id(self, requested_id: UUID) -> ProfileRecord | None:
            assert requested_id == user_id
            return ProfileRecord(
                id=user_id,
                display_name="总管理员",
                role="teacher",
                status="invited",
            )

        async def promote_invited_to_admin(
            self,
            requested_id: UUID,
            display_name: str,
        ) -> bool:
            raise AssertionError("已消费的邀请不得提升为管理员")

    service = AccountService(gateway=StubGateway(), profiles=StubProfiles())  # type: ignore[arg-type]

    with pytest.raises(AccountStateError, match="尚未激活"):
        await service.bootstrap_admin(
            email="admin@example.edu",
            display_name="总管理员",
        )


@pytest.mark.anyio
async def test_bootstrap_admin_sends_the_first_invitation_when_email_is_new() -> None:
    user_id = UUID("11111111-1111-1111-1111-111111111111")
    invited_user = AuthUser(
        id=user_id,
        email="admin@example.edu",
        invited_at=datetime(2026, 7, 14, tzinfo=UTC),
        created_at=datetime(2026, 7, 14, tzinfo=UTC),
        last_sign_in_at=None,
        banned_until=None,
    )

    class StubGateway:
        async def list_users(self, *, page: int, per_page: int) -> list[AuthUser]:
            return []

        async def invite_teacher(self, *, email: str, display_name: str) -> AuthUser:
            assert (email, display_name) == ("admin@example.edu", "总管理员")
            return invited_user

    class StubProfiles:
        def __init__(self) -> None:
            self.profile = ProfileRecord(
                id=user_id,
                display_name="总管理员",
                role="teacher",
                status="invited",
            )

        async def get_admin(self) -> ProfileRecord | None:
            return None

        async def get_by_id(self, requested_id: UUID) -> ProfileRecord | None:
            return self.profile

        async def promote_invited_to_admin(
            self,
            requested_id: UUID,
            display_name: str,
        ) -> bool:
            self.profile = self.profile.model_copy(update={"role": "admin", "status": "active"})
            return True

    service = AccountService(gateway=StubGateway(), profiles=StubProfiles())  # type: ignore[arg-type]

    account = await service.bootstrap_admin(
        email="admin@example.edu",
        display_name="总管理员",
    )

    assert account.role == "admin"
