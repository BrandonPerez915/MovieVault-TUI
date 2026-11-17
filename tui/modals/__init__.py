"""
Interactive modals package for MovieVault (`tui/modals/`).
"""

from tui.modals.admin_crud import AdminEditModal, AdminEntityDetailModal
from tui.modals.auth import UserMenuModal, UserSwitchModal
from tui.modals.common import ConfirmModal
from tui.modals.lists import AddMovieToListModal, CreateListModal, ManageListModal
from tui.modals.profile import (
    EditProfileModal,
    FollowListModal,
    SocialActionModal,
    UploadAvatarModal,
    VisitProfileModal,
    WrappedModal,
)
from tui.modals.review import RATING_OPTIONS, ReviewMovieModal, SearchReviewsModal

__all__ = [
    "RATING_OPTIONS",
    "AddMovieToListModal",
    "AdminEditModal",
    "AdminEntityDetailModal",
    "ConfirmModal",
    "CreateListModal",
    "EditProfileModal",
    "FollowListModal",
    "ManageListModal",
    "ReviewMovieModal",
    "SearchReviewsModal",
    "SocialActionModal",
    "UploadAvatarModal",
    "UserMenuModal",
    "UserSwitchModal",
    "VisitProfileModal",
    "WrappedModal",
]
