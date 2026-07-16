"""认证层公开数据结构。"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class CurrentAccount(BaseModel):
    """当前访问者在应用内的角色与状态。"""

    id: UUID
    email: str
    display_name: str
    role: Literal["admin", "teacher"]
    status: Literal["invited", "active", "disabled"]


class ProfileRecord(BaseModel):
    """数据库中可信的应用账户字段。"""

    id: UUID
    display_name: str
    role: Literal["admin", "teacher"]
    status: Literal["invited", "active", "disabled"]


class TeacherAccount(BaseModel):
    """管理员教师列表中的安全字段。"""

    id: UUID
    email: str
    display_name: str
    status: Literal["invited", "active", "disabled"]
    invited_at: datetime | None
