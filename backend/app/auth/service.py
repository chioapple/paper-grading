"""账户管理用例。"""

from uuid import UUID

from app.auth.models import CurrentAccount, ProfileRecord, TeacherAccount
from app.auth.repository import ProfileRepository
from app.auth.supabase import AuthUser, SupabaseAuthGateway


class AccountSyncError(RuntimeError):
    """Auth 用户与 profile 不一致。"""


class AccountStateError(RuntimeError):
    """账户状态不允许当前转换。"""


class AccountService:
    """协调 Supabase Auth 与应用 profile。"""

    def __init__(
        self,
        *,
        gateway: SupabaseAuthGateway,
        profiles: ProfileRepository,
    ) -> None:
        self._gateway = gateway
        self._profiles = profiles

    async def list_teachers(self) -> list[TeacherAccount]:
        """只列出同时存在 Auth 用户和受控 teacher profile 的账户。"""

        auth_users = await self._list_all_auth_users()
        profiles = await self._profiles.list_by_ids({user.id for user in auth_users})
        profile_by_id = {profile.id: profile for profile in profiles}

        teachers: list[TeacherAccount] = []
        for user in auth_users:
            profile = profile_by_id.get(user.id)
            if profile is None or profile.role != "teacher":
                continue
            teachers.append(
                TeacherAccount(
                    id=user.id,
                    email=user.email,
                    display_name=profile.display_name,
                    status=profile.status,
                    invited_at=user.invited_at,
                )
            )
        return teachers

    async def _list_all_auth_users(self) -> list[AuthUser]:
        per_page = 1000
        page = 1
        auth_users: list[AuthUser] = []
        while True:
            current_page = await self._gateway.list_users(page=page, per_page=per_page)
            auth_users.extend(current_page)
            if len(current_page) < per_page:
                break
            page += 1
        return auth_users

    async def bootstrap_admin(self, *, email: str, display_name: str) -> CurrentAccount:
        """发送首个管理员邀请，并把其 profile 提升为唯一总管理员。"""

        normalized_email = email.strip().lower()
        normalized_name = display_name.strip()
        existing_admin = await self._profiles.get_admin()
        auth_users = await self._list_all_auth_users()
        matches = [user for user in auth_users if user.email.lower() == normalized_email]
        if existing_admin is not None:
            if (
                len(matches) != 1
                or existing_admin.id != matches[0].id
                or existing_admin.status != "active"
            ):
                raise AccountStateError("系统已经存在其他总管理员")
            return CurrentAccount(
                id=existing_admin.id,
                email=matches[0].email,
                display_name=existing_admin.display_name,
                role="admin",
                status="active",
            )
        if len(matches) > 1:
            raise AccountSyncError("Supabase Auth 存在重复管理员邮箱")
        auth_user = (
            matches[0]
            if matches
            else await self._gateway.invite_teacher(
                email=normalized_email,
                display_name=normalized_name,
            )
        )
        profile = await self._profiles.get_by_id(auth_user.id)
        if (
            profile is None
            or profile.role != "teacher"
            or profile.status != "invited"
            or auth_user.invited_at is None
            or auth_user.last_sign_in_at is not None
        ):
            raise AccountStateError("管理员必须来自尚未激活的 Supabase 邀请")
        changed = await self._profiles.promote_invited_to_admin(
            auth_user.id,
            normalized_name,
        )
        promoted = await self._profiles.get_by_id(auth_user.id)
        if (
            not changed
            or promoted is None
            or promoted.role != "admin"
            or promoted.status != "active"
        ):
            raise AccountSyncError("总管理员引导失败")
        return CurrentAccount(
            id=promoted.id,
            email=auth_user.email,
            display_name=promoted.display_name,
            role="admin",
            status="active",
        )

    async def invite_teacher(self, *, email: str, display_name: str) -> TeacherAccount:
        """发送邀请，并确认数据库触发器同步了受控 profile。"""

        normalized_email = email.strip().lower()
        existing_users = await self._list_all_auth_users()
        if any(user.email.lower() == normalized_email for user in existing_users):
            raise AccountStateError("邮箱已经存在")
        normalized_name = display_name.strip()
        user = await self._gateway.invite_teacher(
            email=normalized_email,
            display_name=normalized_name,
        )
        profile = await self._profiles.get_by_id(user.id)
        if (
            profile is None
            or profile.role != "teacher"
            or profile.status != "invited"
            or profile.display_name != normalized_name
        ):
            raise AccountSyncError("邀请账户未生成匹配的 teacher profile")
        return TeacherAccount(
            id=user.id,
            email=user.email,
            display_name=profile.display_name,
            status=profile.status,
            invited_at=user.invited_at,
        )

    async def complete_invite(self, user_id: UUID) -> ProfileRecord:
        """幂等完成邀请；教师从 invited 激活，已引导管理员保持 active。"""

        profile = await self._profiles.get_by_id(user_id)
        if profile is not None and profile.role == "admin" and profile.status == "active":
            return profile
        if profile is None or profile.role != "teacher":
            raise AccountStateError("账户不能完成教师邀请")
        if profile.status == "active":
            return profile
        if profile.status != "invited":
            raise AccountStateError("账户不能完成教师邀请")
        changed = await self._profiles.activate_invited(profile.id)
        activated = await self._profiles.get_by_id(profile.id)
        if not changed or activated is None or activated.status != "active":
            raise AccountStateError("教师邀请状态转换失败")
        return activated

    async def disable_teacher(self, user_id: UUID) -> ProfileRecord:
        """先关闭应用权限，再幂等确认 Supabase Auth 账户已封禁。"""

        profile = await self._profiles.get_by_id(user_id)
        if (
            profile is None
            or profile.role != "teacher"
            or profile.status not in {"active", "disabled"}
        ):
            raise AccountStateError("只有正常教师账户可以停用")
        if profile.status == "active":
            changed = await self._profiles.disable_active(user_id)
            if not changed:
                raise AccountStateError("教师账户状态已变化")
        auth_user = await self._gateway.disable_user(user_id)
        if auth_user.banned_until is None:
            raise AccountSyncError("Supabase Auth 未确认账户封禁")
        disabled = await self._profiles.get_by_id(user_id)
        if disabled is None or disabled.status != "disabled":
            raise AccountStateError("教师账户停用失败")
        return disabled

    async def enable_teacher(self, user_id: UUID) -> ProfileRecord:
        """先解除 Auth 封禁，再打开应用权限。"""

        profile = await self._profiles.get_by_id(user_id)
        if profile is None or profile.role != "teacher" or profile.status != "disabled":
            raise AccountStateError("只有已停用教师账户可以启用")
        auth_user = await self._gateway.enable_user(user_id)
        if auth_user.banned_until is not None:
            raise AccountSyncError("Supabase Auth 未确认解除封禁")
        changed = await self._profiles.enable_disabled(user_id)
        if not changed:
            raise AccountStateError("教师账户状态已变化")
        enabled = await self._profiles.get_by_id(user_id)
        if enabled is None or enabled.status != "active":
            raise AccountStateError("教师账户启用失败")
        return enabled
