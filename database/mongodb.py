"""
Database layer — MongoDB with Motor (async).
Collections: users, files, channels, broadcasts, stats
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import motor.motor_asyncio
from pymongo import ASCENDING, DESCENDING, IndexModel

logger = logging.getLogger(__name__)


class Database:
    client: motor.motor_asyncio.AsyncIOMotorClient = None
    db: motor.motor_asyncio.AsyncIOMotorDatabase = None

    # ─── Connection ───────────────────────────────────────────

    @classmethod
    async def connect(cls, uri: str, db_name: str) -> None:
        cls.client = motor.motor_asyncio.AsyncIOMotorClient(uri)
        cls.db = cls.client[db_name]
        await cls._create_indexes()
        logger.info(f"Connected to MongoDB: {db_name}")

    @classmethod
    async def disconnect(cls) -> None:
        if cls.client:
            cls.client.close()

    @classmethod
    async def _create_indexes(cls) -> None:
        """Create indexes for performance."""
        # Users
        await cls.db.users.create_indexes([
            IndexModel([("user_id", ASCENDING)], unique=True),
            IndexModel([("username", ASCENDING)]),
            IndexModel([("joined_at", DESCENDING)]),
            IndexModel([("referral_code", ASCENDING)], unique=True, sparse=True),
        ])
        # Files
        await cls.db.files.create_indexes([
            IndexModel([("file_id", ASCENDING)], unique=True),
            IndexModel([("owner_id", ASCENDING)]),
            IndexModel([("file_key", ASCENDING)], unique=True),
            IndexModel([("uploaded_at", DESCENDING)]),
            IndexModel([("file_name", ASCENDING)]),
            IndexModel([("tags", ASCENDING)]),
            IndexModel([("is_public", ASCENDING)]),
        ])
        # Stats
        await cls.db.stats.create_indexes([
            IndexModel([("date", DESCENDING)]),
        ])

    # ─── User Operations ─────────────────────────────────────

    @classmethod
    async def add_user(cls, user_id: int, username: str, first_name: str,
                       referral_by: Optional[int] = None) -> Dict[str, Any]:
        """Add new user or return existing."""
        import secrets
        existing = await cls.db.users.find_one({"user_id": user_id})
        if existing:
            # Update last_seen
            await cls.db.users.update_one(
                {"user_id": user_id},
                {"$set": {"last_seen": datetime.utcnow(), "username": username, "first_name": first_name}}
            )
            return existing

        referral_code = secrets.token_urlsafe(8)
        user_doc = {
            "user_id": user_id,
            "username": username,
            "first_name": first_name,
            "joined_at": datetime.utcnow(),
            "last_seen": datetime.utcnow(),
            "is_banned": False,
            "is_admin": False,
            "total_uploads": 0,
            "total_downloads": 0,
            "storage_used_bytes": 0,
            "referral_code": referral_code,
            "referral_by": referral_by,
            "referral_count": 0,
            "plan": "free",  # free / premium
            "plan_expiry": None,
        }
        await cls.db.users.insert_one(user_doc)

        # Credit referral
        if referral_by:
            await cls.db.users.update_one(
                {"user_id": referral_by},
                {"$inc": {"referral_count": 1}}
            )
        return user_doc

    @classmethod
    async def get_user(cls, user_id: int) -> Optional[Dict[str, Any]]:
        return await cls.db.users.find_one({"user_id": user_id})

    @classmethod
    async def ban_user(cls, user_id: int) -> bool:
        result = await cls.db.users.update_one(
            {"user_id": user_id}, {"$set": {"is_banned": True}}
        )
        return result.modified_count > 0

    @classmethod
    async def unban_user(cls, user_id: int) -> bool:
        result = await cls.db.users.update_one(
            {"user_id": user_id}, {"$set": {"is_banned": False}}
        )
        return result.modified_count > 0

    @classmethod
    async def get_all_users(cls, banned: Optional[bool] = None) -> List[Dict]:
        query = {}
        if banned is not None:
            query["is_banned"] = banned
        cursor = cls.db.users.find(query, {"user_id": 1, "username": 1, "first_name": 1})
        return await cursor.to_list(length=None)

    @classmethod
    async def count_users(cls) -> int:
        return await cls.db.users.count_documents({})

    @classmethod
    async def count_active_today(cls) -> int:
        since = datetime.utcnow() - timedelta(hours=24)
        return await cls.db.users.count_documents({"last_seen": {"$gte": since}})

    @classmethod
    async def get_referral_leaderboard(cls, limit: int = 10) -> List[Dict]:
        cursor = cls.db.users.find(
            {"referral_count": {"$gt": 0}},
            {"user_id": 1, "first_name": 1, "referral_count": 1}
        ).sort("referral_count", DESCENDING).limit(limit)
        return await cursor.to_list(length=None)

    @classmethod
    async def get_user_by_referral_code(cls, code: str) -> Optional[Dict]:
        return await cls.db.users.find_one({"referral_code": code})

    # ─── File Operations ─────────────────────────────────────

    @classmethod
    async def save_file(cls,
                        file_key: str,
                        owner_id: int,
                        file_id: str,
                        file_name: str,
                        file_size: int,
                        file_type: str,
                        message_id: int,
                        is_encrypted: bool = False,
                        password_hash: Optional[str] = None,
                        tags: Optional[List[str]] = None,
                        caption: Optional[str] = None) -> Dict[str, Any]:
        """Save file metadata to DB."""
        doc = {
            "file_key": file_key,
            "owner_id": owner_id,
            "file_id": file_id,
            "file_name": file_name,
            "file_size": file_size,
            "file_type": file_type,
            "message_id": message_id,
            "is_encrypted": is_encrypted,
            "password_hash": password_hash,
            "tags": tags or [],
            "caption": caption or "",
            "uploaded_at": datetime.utcnow(),
            "download_count": 0,
            "is_public": False,
            "is_deleted": False,
            "auto_delete_at": None,
        }
        await cls.db.files.insert_one(doc)
        await cls.db.users.update_one(
            {"user_id": owner_id},
            {"$inc": {"total_uploads": 1, "storage_used_bytes": file_size}}
        )
        await cls._record_stat("upload", owner_id)
        return doc

    @classmethod
    async def get_file(cls, file_key: str) -> Optional[Dict[str, Any]]:
        return await cls.db.files.find_one({"file_key": file_key, "is_deleted": False})

    @classmethod
    async def get_user_files(cls, owner_id: int, page: int = 1, per_page: int = 10) -> List[Dict]:
        skip = (page - 1) * per_page
        cursor = cls.db.files.find(
            {"owner_id": owner_id, "is_deleted": False}
        ).sort("uploaded_at", DESCENDING).skip(skip).limit(per_page)
        return await cursor.to_list(length=None)

    @classmethod
    async def count_user_files(cls, owner_id: int) -> int:
        return await cls.db.files.count_documents({"owner_id": owner_id, "is_deleted": False})

    @classmethod
    async def delete_file(cls, file_key: str, owner_id: int) -> bool:
        file = await cls.get_file(file_key)
        if not file or file["owner_id"] != owner_id:
            return False
        await cls.db.files.update_one(
            {"file_key": file_key},
            {"$set": {"is_deleted": True}}
        )
        await cls.db.users.update_one(
            {"user_id": owner_id},
            {"$inc": {"storage_used_bytes": -file.get("file_size", 0)}}
        )
        return True

    @classmethod
    async def rename_file(cls, file_key: str, owner_id: int, new_name: str) -> bool:
        result = await cls.db.files.update_one(
            {"file_key": file_key, "owner_id": owner_id, "is_deleted": False},
            {"$set": {"file_name": new_name}}
        )
        return result.modified_count > 0

    @classmethod
    async def set_file_password(cls, file_key: str, owner_id: int, password_hash: Optional[str]) -> bool:
        is_encrypted = password_hash is not None
        result = await cls.db.files.update_one(
            {"file_key": file_key, "owner_id": owner_id, "is_deleted": False},
            {"$set": {"is_encrypted": is_encrypted, "password_hash": password_hash}}
        )
        return result.modified_count > 0

    @classmethod
    async def increment_download(cls, file_key: str) -> None:
        await cls.db.files.update_one(
            {"file_key": file_key},
            {"$inc": {"download_count": 1}}
        )
        await cls._record_stat("download")

    @classmethod
    async def toggle_public(cls, file_key: str, owner_id: int) -> Optional[bool]:
        file = await cls.get_file(file_key)
        if not file or file["owner_id"] != owner_id:
            return None
        new_val = not file.get("is_public", False)
        await cls.db.files.update_one(
            {"file_key": file_key},
            {"$set": {"is_public": new_val}}
        )
        return new_val

    @classmethod
    async def search_files(cls, owner_id: int, query: str) -> List[Dict]:
        """Search files by name or tags."""
        cursor = cls.db.files.find({
            "owner_id": owner_id,
            "is_deleted": False,
            "$or": [
                {"file_name": {"$regex": query, "$options": "i"}},
                {"tags": {"$in": [query.lower()]}},
                {"caption": {"$regex": query, "$options": "i"}},
            ]
        }).sort("uploaded_at", DESCENDING).limit(20)
        return await cursor.to_list(length=None)

    @classmethod
    async def count_total_files(cls) -> int:
        return await cls.db.files.count_documents({"is_deleted": False})

    @classmethod
    async def get_expired_files(cls) -> List[Dict]:
        now = datetime.utcnow()
        cursor = cls.db.files.find({
            "auto_delete_at": {"$lte": now, "$ne": None},
            "is_deleted": False
        })
        return await cursor.to_list(length=None)

    # ─── Channel Operations ──────────────────────────────────

    @classmethod
    async def get_force_channels(cls) -> List[Dict]:
        cursor = cls.db.channels.find({"active": True})
        return await cursor.to_list(length=None)

    @classmethod
    async def add_channel(cls, channel_id: str, channel_name: str) -> None:
        await cls.db.channels.update_one(
            {"channel_id": channel_id},
            {"$set": {"channel_id": channel_id, "channel_name": channel_name, "active": True, "added_at": datetime.utcnow()}},
            upsert=True
        )

    @classmethod
    async def remove_channel(cls, channel_id: str) -> bool:
        result = await cls.db.channels.update_one(
            {"channel_id": channel_id}, {"$set": {"active": False}}
        )
        return result.modified_count > 0

    # ─── Stats ────────────────────────────────────────────────

    @classmethod
    async def _record_stat(cls, action: str, user_id: Optional[int] = None) -> None:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        await cls.db.stats.update_one(
            {"date": today},
            {"$inc": {action: 1}},
            upsert=True
        )

    @classmethod
    async def get_stats(cls) -> Dict[str, Any]:
        total_users = await cls.count_users()
        total_files = await cls.count_total_files()
        active_today = await cls.count_active_today()

        pipeline = [
            {"$group": {"_id": None, "total_storage": {"$sum": "$storage_used_bytes"}}}
        ]
        storage_result = await cls.db.users.aggregate(pipeline).to_list(length=1)
        total_storage = storage_result[0]["total_storage"] if storage_result else 0

        today_stats = await cls.db.stats.find_one({"date": datetime.utcnow().strftime("%Y-%m-%d")}) or {}

        return {
            "total_users": total_users,
            "total_files": total_files,
            "active_today": active_today,
            "total_storage_bytes": total_storage,
            "today_uploads": today_stats.get("upload", 0),
            "today_downloads": today_stats.get("download", 0),
        }
