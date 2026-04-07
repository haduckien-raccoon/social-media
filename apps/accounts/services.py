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
    """Đăng ký user mới, tạo verification token và gửi email xác thực.

    Input: username (str), email (str), password (str).
    Output: (User, None) nếu thành công, (None, error_message) nếu thất bại.
    """
    import logging
    logger = logging.getLogger(__name__)

    # Validate input
    if not username or not username.strip():
        return None, "Username is required"
    if not email or not email.strip():
        return None, "Email is required"
    if not password or len(password) < 6:
        return None, "Password must be at least 6 characters"

    username = username.strip()
    email = email.strip().lower()

    # Check trùng
    if User.objects.filter(email=email).exists():
        logger.info("register_duplicate_email", extra={"email": email})
        return None, "Email already exists"
    if User.objects.filter(username=username).exists():
        logger.info("register_duplicate_username", extra={"username": username})
        return None, "Username already exists"

    try:
        # Tạo user với is_active=True để có thể đăng nhập ngay (dev mode)
        # Trong production, nên dùng email verification
        user = User.objects.create_user(
            username=username, 
            email=email, 
            password=password,
            is_active=True
        )
        
        # Tạo UserProfile mặc định
        UserProfile.objects.get_or_create(user=user)
        
    except Exception as exc:
        logger.exception("register_create_user_failed")
        return None, "Failed to create user account"

    # Tạo token email và gửi mail
    try:
        token = EmailVerificationToken.objects.create(
            user=user,
            expires_at=timezone.now() + timedelta(hours=1)
        )
        verify_url = f"{settings.APP_PUBLIC_BASE_URL}/accounts/verify-email?token={token.token}"
        send_mail('Verify email', f'Click: {verify_url}', settings.EMAIL_HOST_USER, [user.email])
    except Exception as exc:
        logger.warning(
            "register_send_email_failed",
            extra={"email": email, "error": str(exc)},
        )

    return user, None

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

    try:
        # Kích hoạt user và đánh dấu token đã dùng
        token.is_used = True
        token.save()
        token.user.is_active = True
        token.user.save()
        user = token.user
        # Tạo profile mặc định nếu chưa có
        if not hasattr(user, 'userprofile'):
            UserProfile.objects.create(user=user)
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
