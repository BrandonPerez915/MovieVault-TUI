"""
Authentication service for MovieVault (backend/services/AuthService.py).
Persists and authenticates users directly against MongoDB ('users' collection)
with bcrypt password hashing, unique index enforcement, and initial User node
creation in Dgraph.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import re
from typing import Any, Dict, List, Optional, Tuple

import bcrypt
from bson import ObjectId
import pydgraph
from pymongo import ASCENDING
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from databases.mongodb import MongoConnection
from databases.dgraph import DgraphConnection

DEMO_DEFAULT_PASSWORD = "demo123"


@dataclass
class UserSession:
    """Represents the currently authenticated user session in the TUI."""
    user_id: str
    username: str
    email: str
    favorite_genres: List[str] = field(default_factory=list)
    lists_count: int = 0
    is_live_db: bool = True
    avatar_url: str = ""


def hash_password(raw_password: str) -> str:
    """Hashes a plaintext password using bcrypt."""
    salt = bcrypt.gensalt(rounds=10)
    hashed = bcrypt.hashpw(raw_password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def check_password(raw_password: str, stored_hash: str) -> bool:
    """Verifies a plaintext password against a stored bcrypt hash."""
    if not stored_hash or not raw_password:
        return False
    try:
        return bcrypt.checkpw(
            raw_password.encode("utf-8"),
            stored_hash.encode("utf-8"),
        )
    except ValueError:
        return False


class AuthService:
    """
    Manages user authentication, registration, and session switching directly
    against MongoDB ('users' collection) and Dgraph (Singleton).
    """

    _instance: Optional["AuthService"] = None

    def __new__(cls, *args: Any, **kwargs: Any) -> "AuthService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._current_session: Optional[UserSession] = None
        self._indexes_ensured: bool = False
        self._initialized = True

    def _get_users_collection(self) -> Optional[Collection]:
        """Returns the live MongoDB 'users' collection and ensures unique indexes."""
        try:
            mongo = MongoConnection()
            if not mongo.initialized or mongo.database is None:
                return None
            users_col: Collection = mongo.database["users"]
        except Exception:
            return None

        if not self._indexes_ensured:
            try:
                users_col.create_index(
                    [("username", ASCENDING)],
                    unique=True,
                    name="idx_unique_username",
                )
                users_col.create_index(
                    [("email", ASCENDING)],
                    unique=True,
                    name="idx_unique_email",
                )
                self._indexes_ensured = True
            except Exception:
                pass
        return users_col

    def _create_dgraph_user_node(self, user_id: str, username: str, email: str) -> None:
        """Creates the initial User node in Dgraph when a new user registers."""
        try:
            dgraph = DgraphConnection()
            if not dgraph.initialized or dgraph.client is None:
                return
            client = dgraph.client
        except Exception:
            return

        txn = client.txn()
        try:
            nquads_payload = {
                "uid": f"_:{username}",
                "dgraph.type": "User",
                "user_id": user_id,
                "username": username,
                "email": email,
                "followers": 0,
                "views_count": 0,
            }
            mutation = pydgraph.Mutation(
                set_json=json.dumps(nquads_payload).encode("utf-8")
            )
            txn.mutate(mutation, commit_now=True)
        except Exception:
            pass
        finally:
            txn.discard()

    @property
    def current_session(self) -> Optional[UserSession]:
        """Returns the currently authenticated user session."""
        return self._current_session

    def list_demo_users(self) -> List[Dict[str, Any]]:
        """Returns registered users stored in MongoDB for quick session switching."""
        collection = self._get_users_collection()
        if collection is None:
            return []

        users_list: List[Dict[str, Any]] = []
        try:
            cursor = collection.find(
                {},
                {"username": 1, "email": 1, "lists": 1},
            ).sort("created_at", -1).limit(20)
            for doc in cursor:
                users_list.append({
                    "user_id": str(doc["_id"]),
                    "username": doc.get("username", ""),
                    "email": doc.get("email", ""),
                    "favorite_genres": [],
                    "lists_count": len(doc.get("lists", [])),
                })
        except Exception:
            pass
        return users_list

    def login(self, username: str, password: str) -> Tuple[bool, Optional[UserSession], str]:
        """
        Authenticates a user by username and password against MongoDB's 'users' collection.
        Returns (success, session, message).
        """
        clean_user = (username or "").strip()
        if not clean_user or not password:
            return False, None, "You must enter your username and password."

        collection = self._get_users_collection()
        if collection is None:
            return (
                False,
                None,
                "MongoDB is not connected. Verify that the MongoDB instance is active.",
            )

        try:
            user_doc = collection.find_one({"username": clean_user})
            if not user_doc:
                return (
                    False,
                    None,
                    f"User '@{clean_user}' does not exist in the database. Register with Ctrl+R.",
                )

            stored_hash = user_doc.get("password_hash", "")
            if not check_password(password, stored_hash):
                return False, None, "Incorrect password."

            session = UserSession(
                user_id=str(user_doc["_id"]),
                username=user_doc["username"],
                email=user_doc.get("email", ""),
                lists_count=len(user_doc.get("lists", [])),
                is_live_db=True,
            )
            self._current_session = session
            return True, session, f"Successfully logged in as @{clean_user}"
        except Exception as exc:
            return False, None, f"Error querying MongoDB: {exc}"

    def register(
        self,
        username: str,
        email: str,
        password: str,
        confirm_password: str,
    ) -> Tuple[bool, Optional[UserSession], str]:
        """
        Registers a new user in MongoDB ('users' collection) enforcing unique
        constraints on username and email and storing a bcrypt password_hash.
        Also initializes the user node in Dgraph if connected.
        """
        clean_user = (username or "").strip()
        clean_email = (email or "").strip().lower()

        if not clean_user or not clean_email or not password:
            return False, None, "All fields (username, email, and password) are required."

        if len(clean_user) < 3 or not re.match(r"^[a-zA-Z0-9_.-]+$", clean_user):
            return False, None, "Username must have at least 3 alphanumeric characters or '_'."

        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", clean_email):
            return False, None, "Invalid email format."

        if len(password) < 6:
            return False, None, "Password must have at least 6 characters."

        if password != confirm_password:
            return False, None, "Password and confirmation do not match."

        collection = self._get_users_collection()
        if collection is None:
            return (
                False,
                None,
                "Could not register: MongoDB is not connected or available.",
            )

        pwd_hash = hash_password(password)
        now = datetime.now(timezone.utc)

        new_doc: Dict[str, Any] = {
            "username": clean_user,
            "email": clean_email,
            "password_hash": pwd_hash,
            "created_at": now,
            "lists": [],
        }

        try:
            res = collection.insert_one(new_doc)
            inserted_id = str(res.inserted_id)

            # Initialize User node in Dgraph if Dgraph is online
            self._create_dgraph_user_node(inserted_id, clean_user, clean_email)

            session = UserSession(
                user_id=inserted_id,
                username=clean_user,
                email=clean_email,
                lists_count=0,
                is_live_db=True,
            )
            self._current_session = session
            return True, session, f"User @{clean_user} successfully saved in MongoDB."
        except DuplicateKeyError:
            return (
                False,
                None,
                "MongoDB Unique Index Error: username or email is already registered.",
            )
        except Exception as exc:
            return False, None, f"Error saving user in MongoDB: {exc}"

    def quick_switch_user(self, username: str) -> Tuple[bool, Optional[UserSession], str]:
        """Switches active session to an existing user stored in MongoDB."""
        collection = self._get_users_collection()
        if collection is None:
            return False, None, "MongoDB is not connected."

        try:
            doc = collection.find_one({"username": username})
            if not doc:
                return False, None, f"User @{username} not found in MongoDB."

            session = UserSession(
                user_id=str(doc["_id"]),
                username=doc["username"],
                email=doc.get("email", ""),
                lists_count=len(doc.get("lists", [])),
                is_live_db=True,
            )
            self._current_session = session
            return True, session, f"Active user changed to @{username}"
        except Exception as exc:
            return False, None, f"Error switching user: {exc}"

    def update_current_session(self, session: UserSession) -> None:
        """Replaces the active in-memory session after profile edits."""
        self._current_session = session

    def logout(self) -> None:
        """Clears the current user session."""
        self._current_session = None
