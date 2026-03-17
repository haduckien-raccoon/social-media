from os import error
import jwt
from datetime import datetime, timedelta
from django.conf import settings
from .models import RefreshToken, PasswordResetToken
from django.utils import timezone
from django.utils import timezone
from datetime import timedelta
from django.core.mail import send_mail
from .models import User, EmailVerificationToken, UserProfile
from django.conf import settings
from django.db.models import Q
from apps.friends.models import *

JWT_SECRET = settings.SECRET_KEY
JWT_ALGORITHM = 'HS256'

def create_jwt_pair_for_user(user):
    access_payload = {
        'user_id': user.id,
        'email': user.email,
        'exp': (timezone.now() + timedelta(minutes=15)),
        'type': 'access'
    }
    access_token = jwt.encode(access_payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    
    refresh_payload = {
        'user_id': user.id,
        'email': user.email,
        'exp': (timezone.now() + timedelta(days=7)),
        'type': 'refresh'
    }
    refresh_token = jwt.encode(refresh_payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

    RefreshToken.objects.create(
        user=user,
        token=refresh_token,
        expires_at=timezone.now() + timedelta(days=7)
    )

    return access_token, refresh_token

def decode_jwt(token, verify_exp=True):
    try:
        return jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            options={"verify_exp": verify_exp}
        )
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

def create_password_reset_token(user):
    token = PasswordResetToken.objects.create(
        user=user,
        expires_at=timezone.now() + timedelta(hours=2)
    )
    return token

def register_user(username, email, password):
    # Check trùng
    if User.objects.filter(email=email).exists():
        #in ra log cho dễ debug
        print(f"[DEBUG] Email đã tồn tại: {email}")
        return None, "Email already exists"
    if User.objects.filter(username=username).exists():
        print(f"[DEBUG] Username đã tồn tại: {username}")
        return None, "Username already exists"

    user = User.objects.create(username=username, email=email, password=password)
    # Tạo token email
    token = EmailVerificationToken.objects.create(
        user=user,
        expires_at=timezone.now() + timedelta(hours=1)
    )
    # Gửi mail
    verify_url = f"http://127.0.0.1:8080/accounts/verify-email?token={token.token}"
    send_mail('Verify email', f'Click: {verify_url}', settings.EMAIL_HOST_USER, [user.email])

    return user, None

def create_user_profile(user):
    profile, created = UserProfile.objects.get_or_create(user=user)
    return profile, created

def verify_email_token(token_value):
    """
    Xác thực token email.
    Trả về: success (bool), message (str)
    """
    if not token_value:
        return False, "Token không được để trống."

    try:
        token = EmailVerificationToken.objects.get(token=token_value, is_used=False)
    except EmailVerificationToken.DoesNotExist:
        return False, "Token không hợp lệ hoặc đã sử dụng."
    except Exception as e:
        print(f"[ERROR] Lỗi khi lấy token: {e}")
        return False, "Đã xảy ra lỗi khi truy xuất token."

    # Kiểm tra hết hạn
    if token.expires_at < timezone.now():
        return False, "Token đã hết hạn."
    #tạo profile nếu chưa có
    create_user_profile(token.user)
    token.user.is_verified = True
    #in ra log để debug
    print(f"[DEBUG] Email verified for user: {token.user.email}")
    try:
        # Kích hoạt user và đánh dấu token đã dùng
        token.is_used = True
        token.save()
        token.user.is_active = True
        token.user.save()
        user = token.user
        # Tạo profile mặc định nếu chưa có
    except Exception as e:
        print(f"[ERROR] Lỗi khi cập nhật token/user: {e}")
        return False, "Đã xảy ra lỗi khi xác thực email."
    return True, "Email đã được xác thực thành công! Bạn có thể đăng nhập ngay bây giờ.", user

def login_user(email, password):
    try:
        user = User.objects.get(email=email)
        error = None
    except User.DoesNotExist:
        return None, "Invalid email or password"
    if not user.check_password(password):
        return None, "Invalid email or password"
    if not user.is_active:
        return None, "Account is not active"
    if user.is_banned:
        return None, "Account is banned"
    if not user.is_verified:
        return None, "Email is not verified"
     # Tạo JWT
    return user, error

def logout_user(refresh_token_value):
    try:
        token = RefreshToken.objects.get(token=refresh_token_value)
        token.delete()
        return True
    except RefreshToken.DoesNotExist:
        return False
    except Exception as e:
        print(f"[ERROR] Lỗi khi đăng xuất: {e}")
        return False
    
def refresh_jwt_token(refresh_token_value):
    payload = decode_jwt(refresh_token_value)
    if not payload or payload.get('type') != 'refresh':
        return None, "Invalid refresh token"

    try:
        token_record = RefreshToken.objects.get(token=refresh_token_value)
    except RefreshToken.DoesNotExist:
        return None, "Refresh token not found"

    if token_record.expires_at < (timezone.now()):
        return None, "Refresh token expired"

    user = token_record.user
    new_access_token, new_refresh_token = create_jwt_pair_for_user(user)

    # Xoá token cũ
    token_record.delete()

    return (new_access_token, new_refresh_token), None

def reset_user_password(token_value, new_password):
    try:
        token = PasswordResetToken.objects.get(token=token_value, is_used=False)
    except PasswordResetToken.DoesNotExist:
        return False, "Invalid or used token"

    if token.expires_at < timezone.now():
        return False, "Token expired"

    user = token.user
    user.set_password(new_password)
    user.save()

    token.is_used = True
    token.save()

    return True, "Password has been reset successfully"

def get_profile_by_user_id(user_id):
    try:
        profile = UserProfile.objects.get(user__id=user_id)
        return profile
    except UserProfile.DoesNotExist:
        return None

def update_user_profile(user, full_name=None, address=None, town=None, province=None, nationality=None, school=None, phone_number=None, birth_day=None, bio=None, avatar=None):
    profile, created = UserProfile.objects.get_or_create(user=user)
    if full_name is not None:
        profile.full_name = full_name
    if address is not None:
        profile.address = address
    if town is not None:
        profile.town = town
    if province is not None:
        profile.province = province
    if nationality is not None:
        profile.nationality = nationality
    if school is not None:
        profile.school = school
    if phone_number is not None:
        profile.phone_number = phone_number
    if birth_day is not None:
        profile.birth_day = birth_day
    if bio is not None:
        profile.bio = bio
    if avatar is not None:
        profile.avatar = avatar

    profile.updated_at = timezone.now()
    profile.save()

    return profile

def change_email(user, new_email):
    if User.objects.filter(email=new_email).exclude(id=user.id).exists():
        return False, "Email already in use"

    user.email = new_email
    user.is_verified = False
    user.save()

    # Tạo token email mới
    token = EmailVerificationToken.objects.create(
        user=user,
        expires_at=timezone.now() + timedelta(hours=1)
    )
    # Gửi mail xác thực
    verify_url = f"http://127.0.0.1:8080/accounts/verify-email/?token={token.token}"
    send_mail('Verify new email', f'Click: {verify_url}', settings.EMAIL_HOST_USER, [user.email])
    #đăng xuất user tất cả token
    RefreshToken.objects.filter(user=user).delete()
    return True, "Email change initiated. Please verify your new email."

def change_password(user, old_password, new_password):
    if not user.check_password(old_password):
        return False, "Old password is incorrect"

    user.set_password(new_password)
    user.save()
    return True, "Password changed successfully"

def change_username(user, new_username):
    if User.objects.filter(username=new_username).exclude(id=user.id).exists():
        return False, "Username already in use"

    user.username = new_username
    user.save()
    return True, "Username changed successfully"

def deactivate_account(user):
    user.is_active = False
    user.save()
    return True, "Account deactivated successfully"

def activate_account(user):
    user.is_active = True
    user.save()
    return True, "Account activated successfully"

def ban_account(user):
    user.is_banned = True
    user.save()
    return True, "Account banned successfully"

def unban_account(user):
    user.is_banned = False
    user.save()
    return True, "Account unbanned successfully"
    
def get_user_by_email(email):
    try:
        user = User.objects.get(email=email)
        return user
    except User.DoesNotExist:
        return None
        
def get_user_by_username(username):
    try:
        user = User.objects.get(username=username)
        return user
    except User.DoesNotExist:
        return None

def get_user_by_id(user_id):
    try:
        user = User.objects.get(id=user_id)
        return user
    except User.DoesNotExist:
        return None

def get_friends_list(user):
    """Liệt kê bạn bè để tag vào bài viết"""
    friends = Friend.objects.filter(user=user).select_related('friend')
    return [f.friend for f in friends]

def get_friendship_status(user1, user2):
    if user1 == user2:
        return "self"

    if Friend.objects.filter(
        Q(user=user1, friend=user2) | Q(user=user2, friend=user1)
    ).exists():
        return "friends"

    request = FriendRequest.objects.filter(
        Q(from_user=user1, to_user=user2) |
        Q(from_user=user2, to_user=user1)
    ).first()

    if request:
        if request.status == FriendRequest.STATUS_PENDING:
            if request.from_user == user1:
                return "request_sent"
            return "request_received"

    return "not_friends"