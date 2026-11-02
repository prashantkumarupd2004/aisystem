"""Pydantic schemas. Responses NEVER include any token field."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    email: str
    role: str
    is_active: bool

    model_config = {"from_attributes": True}


class AccountCreate(BaseModel):
    instagram_user_id: str
    username: str
    account_type: str = "BUSINESS"
    # Plain token is accepted once, encrypted immediately, never stored plain.
    access_token: Optional[str] = None
    token_expiry: Optional[datetime] = None


class AccountOut(BaseModel):
    id: int
    instagram_user_id: str
    username: str
    account_type: str
    connection_status: str
    token_expiry: Optional[datetime] = None
    profile_image_url: Optional[str] = None
    drive_folder_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MappingCreate(BaseModel):
    instagram_account_id: int
    drive_folder_id: int
    shared_folder_mode: bool = False
    confirmed_by_admin: bool = False


class MappingOut(BaseModel):
    id: int
    instagram_account_id: int
    drive_folder_id: int
    shared_folder_mode: bool
    is_active: bool
    confirmed_by_admin: bool

    model_config = {"from_attributes": True}


class DashboardStats(BaseModel):
    connected_accounts: int
    active_accounts: int
    accounts_needing_attention: int
    total_videos: int
    scheduled_reels: int
    published_reels: int
    failed_jobs: int
