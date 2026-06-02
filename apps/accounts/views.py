from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse, Http404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.core.mail import send_mail
from django.conf import settings
import jwt
from apps.middleware.utils import generate_jwt_pair_for_user
from django.contrib import messages
from .models import User, PasswordResetToken, EmailVerificationToken, UserProfile
from apps.friends.models import *
from .services import *
from apps.accounts.services import *
from apps.posts.services import *
from apps.friends.services import *


def _profile_form_value(value):
    if value is None:
        return ""

    value = str(value).strip()
    if value.lower() in {"none", "null"}:
        return ""

    return value


def build_profile_form_data(profile):
    return {
        "full_name": _profile_form_value(profile.full_name),
        "bio": _profile_form_value(profile.bio),
        "address": _profile_form_value(profile.address),
        "town": _profile_form_value(profile.town),
        "province": _profile_form_value(profile.province),
        "nationality": _profile_form_value(profile.nationality),
        "school": _profile_form_value(profile.school),
        "phone_number": _profile_form_value(profile.phone_number),
    }


@csrf_exempt
def register_view(request):
    if request.method == "GET":
        return render(request, "accounts/register.html")

    username = request.POST.get("username")
    email = request.POST.get("email")
    password = request.POST.get("password")

    user, error = register_user(username, email, password)

    if error:
        return render(request, "accounts/register.html", {
            "error": error
        })

    return render(request, "accounts/register.html", {
        "message": f"User: {username} registered. Check email: {email} to verify."
    })

#login
@csrf_exempt
def login_view(request):
    if request.method == "GET":
        return render(request, "accounts/login.html")

    email = request.POST.get("email")
    password = request.POST.get("password")

    user, error = login_user(email, password)

    if not user:
        return render(request, "accounts/login.html", {
            "error": error or "Invalid credentials"
        })

    create_user_profile(user)
    access_token, refresh_token = create_jwt_pair_for_user(user)

    response = redirect("home")  # đổi thành URL name của bạn
    response.set_cookie("access", access_token, httponly=True, max_age=15 * 60)
    response.set_cookie("refresh", refresh_token, httponly=True, max_age=7 * 24 * 60 * 60)

    return response

# Logout
@csrf_exempt
def logout_view(request):
    refresh_token = request.COOKIES.get("refresh")

    if refresh_token:
        logout_user(refresh_token)

    response = redirect("/accounts/login")
    response.delete_cookie("access")
    response.delete_cookie("refresh")
    return response

# Forgot password
@csrf_exempt
def forgot_password_view(request):
    if request.method == "GET":
        return render(request, "accounts/forgot_password.html")

    email = request.POST.get("email")

    try:
        user = User.objects.get(email=email)
        token = create_password_reset_token(user)

        reset_url = build_absolute_url(f"/accounts/reset-password/?token={token.token}")
        send_mail(
            "Reset password",
            f"Click here: {reset_url}",
            settings.EMAIL_HOST_USER,
            [user.email],
        )
    except User.DoesNotExist:
        pass  # không leak thông tin email

    return render(request, "accounts/forgot_password.html", {
        "message": f"If email: {email} exists, reset link has been sent."
    })


# Reset password
@csrf_exempt
def reset_password_view(request):
    if request.method == "GET":
        token = request.GET.get("token")
        return render(request, "accounts/reset_password.html", {
            "token": token
        })

    token_value = request.POST.get("token")
    new_password = request.POST.get("password")

    success, message = reset_user_password(token_value, new_password)

    if not success:
        return render(request, "accounts/reset_password.html", {
            "error": message,
            "token": token_value
        })

    return render(request, "accounts/reset_password_success.html", {
        "message": message
    })

# Email verification
from django.shortcuts import render, redirect
from django.utils import timezone
from .models import EmailVerificationToken

@csrf_exempt
def verify_email_view(request):
    token_value = request.GET.get("token")

    if not token_value:
        return render(request, "accounts/verify_email.html", {
            "error": "Invalid verification link."
        })

    try:
        verify_email_token(token_value)
    except EmailVerificationToken.DoesNotExist:
        return render(request, "accounts/verify_email.html", {
            "error": "Token is invalid or already used."
        })

    return render(request, "accounts/verify_email.html", {
        "message": "Email verified successfully. You can login now."
    })

#profile
from django.db.models import Q

@csrf_exempt
def profile_view(request, id=None, username=None):

    access_token = request.COOKIES.get("access")
    if not access_token:
        return redirect("accounts:login")

    try:
        payload = jwt.decode(
            access_token,
            settings.SECRET_KEY,
            algorithms=["HS256"]
        )

        current_user_id = payload.get("user_id")
        current_user = User.objects.get(id=current_user_id)
        if getattr(current_user, "is_deleted", False):
            return redirect("accounts:login")

        if id is not None:
            id = int(id)

        # user đang xem
        if id:
            user = get_object_or_404(User, id=id)
        elif username:
            user = get_object_or_404(User, username=username)
        else:
            user = current_user

        # =================================================================
        # THÊM LOGIC CHECK BLOCK: Nếu có chặn nhau thì báo không tìm thấy
        # =================================================================
        if user != current_user:
            # Lấy trạng thái chặn từ hàm trong services
            block_status = get_block_status(current_user, user)
            
            # Nếu không phải là "not_blocked", nghĩa là đang chặn hoặc bị chặn
            if block_status != "not_blocked":
                raise Http404("Trang này không khả dụng hoặc người dùng không tồn tại.")
        # =================================================================
        #Thêm logic check is_deleted, is_banned, is_active, is_verified: Nếu bị xóa, bị ban, bị unactivate, chưa verified thì báo không tìm thấy
        if user.is_deleted or user.is_banned or not user.is_active or not user.is_verified:
            raise Http404("Trang này không khả dụng hoặc người dùng không tồn tại.")
        # =================================================================

        # posts + friends
        if user == current_user:
            friends = get_friends_list(current_user)
            posts = get_my_posts(current_user)
        else:
            friends = get_friends_list(user)
            friends_ids = [f.id for f in friends]
            posts = get_user_posts(current_user, user, friends_ids)

        # friendship status
        if user != current_user:
            friendship_status = get_friendship_status(current_user, user)
        else:
            friendship_status = "self"

        # luôn khởi tạo
        request_obj = None

        if friendship_status in ["request_sent", "request_received"]:
            request_obj = FriendRequest.objects.filter(
                Q(from_user=current_user, to_user=user) |
                Q(from_user=user, to_user=current_user),
                status=FriendRequest.STATUS_PENDING
            ).first()

        count_friends = len(friends)

        profile = get_object_or_404(UserProfile, user=user)

        if profile.bio is None:
            profile.bio = ""

        return render(request, "accounts/profile.html", {
            "user": user,
            "profile": profile,
            "current_user": current_user,
            "friends": friends,
            "count_friends": count_friends,
            "posts": posts,
            "friendship_status": friendship_status,
            "request_id": request_obj.id if request_obj else None
        })

    except (jwt.ExpiredSignatureError, jwt.DecodeError, User.DoesNotExist):
        return redirect("accounts:login")

@csrf_exempt
def edit_profile_view(request):
    access_token = request.COOKIES.get("access")
    if not access_token:
        return redirect("accounts:login")

    try:
        payload = jwt.decode(
            access_token,
            settings.SECRET_KEY,
            algorithms=["HS256"]
        )
        user_id = payload.get("user_id")
        user = User.objects.get(id=user_id)
        if getattr(user, "is_deleted", False):
            return redirect("accounts:login")
        profile = get_object_or_404(UserProfile, user=user)

        if request.method == "GET":
            return render(request, "accounts/edit_profile.html", {
                "user": user,
                "profile": profile,
                "profile_form": build_profile_form_data(profile),
            })

        # POST: cập nhật profile
        full_name = request.POST.get("full_name", "")
        bio = request.POST.get("bio", "")
        address = request.POST.get("address", "")
        town = request.POST.get("town", "")
        province = request.POST.get("province", "")
        nationality = request.POST.get("nationality", "")
        school = request.POST.get("school", "")
        phone_number = request.POST.get("phone_number", "")

        # Không nhập ngày sinh thì tự lưu mặc định 01/01/2000.
        birth_day = request.POST.get("birth_day", "").strip() or "2000-01-01"

        # Cập nhật avatar nếu có upload.
        avatar = request.FILES.get("avatar")

        profile = update_user_profile(
            user,
            full_name=full_name,
            bio=bio,
            address=address,
            town=town,
            province=province,
            nationality=nationality,
            school=school,
            phone_number=phone_number,
            birth_day=birth_day,
            avatar=avatar
        )

        return redirect("/accounts/profile/")  # chuyển về trang profile sau khi cập nhật

    except (jwt.ExpiredSignatureError, jwt.DecodeError, User.DoesNotExist):
        return redirect("accounts:login")

@csrf_exempt
def update_email_view(request):
    access_token = request.COOKIES.get("access")
    if not access_token:
        return redirect("accounts:login")

    try:
        payload = jwt.decode(
            access_token,
            settings.SECRET_KEY,
            algorithms=["HS256"]
        )
        user_id = payload.get("user_id")
        user = User.objects.get(id=user_id)
        if getattr(user, "is_deleted", False):
            return redirect("accounts:login")
        profile = get_object_or_404(UserProfile, user=user)

        if request.method == "GET":
            return render(request, "accounts/edit_email.html", {
                "user": user,
                "profile": profile
            })

        # POST: cập nhật email
        new_email = request.POST.get("new_email")
        if new_email:
            is_change, message = change_email(user, new_email)
            if is_change:
                #xóa accessToken và refreshToken cũ
                logout_view(request)
                return render(request, "accounts/login.html", {
                    "message": "Email updated successfully. Please verify your new email."
                })
            else:
                return render(request, "accounts/edit_email.html", {
                    "user": user,
                    "profile": profile,
                    "error": message
                })
        return render(request, "accounts/edit_email.html", {
            "user": user,
            "profile": profile,
            "error": "Please provide a valid email."
        })
    except (jwt.ExpiredSignatureError, jwt.DecodeError, User.DoesNotExist):
        return redirect("accounts:login")
    
@csrf_exempt
def update_username_view(request):
    access_token = request.COOKIES.get("access")
    if not access_token:
        return redirect("accounts:login")

    try:
        payload = jwt.decode(
            access_token,
            settings.SECRET_KEY,
            algorithms=["HS256"]
        )
        user_id = payload.get("user_id")
        user = User.objects.get(id=user_id)
        if getattr(user, "is_deleted", False):
            return redirect("accounts:login")
        profile = get_object_or_404(UserProfile, user=user)

        if request.method == "GET":
            return render(request, "accounts/edit_username.html", {
                "user": user,
                "profile": profile
            })

        # POST: cập nhật username
        new_username = request.POST.get("new_username")
        if new_username:
            is_change, message = change_username(user, new_username)
            if is_change:
                return render(request, "accounts/edit_username.html", {
                    "user": user,
                    "profile": profile,
                    "message": "Username updated successfully."
                })
            else:
                return render(request, "accounts/edit_username.html", {
                    "user": user,
                    "profile": profile,
                    "error": message
                })
        return render(request, "accounts/edit_username.html", {
            "user": user,
            "profile": profile,
            "error": "Please provide a valid username."
        })
    except (jwt.ExpiredSignatureError, jwt.DecodeError, User.DoesNotExist):
        return redirect("accounts:login")
    
@csrf_exempt
def update_password_view(request):
    access_token = request.COOKIES.get("access")
    if not access_token:
        return redirect("accounts:login")

    try:
        payload = jwt.decode(
            access_token,
            settings.SECRET_KEY,
            algorithms=["HS256"]
        )
        user_id = payload.get("user_id")
        user = User.objects.get(id=user_id)
        if getattr(user, "is_deleted", False):
            return redirect("accounts:login")
        profile = get_object_or_404(UserProfile, user=user)

        if request.method == "GET":
            return render(request, "accounts/edit_password.html", {
                "user": user,
                "profile": profile
            })

        # POST: cập nhật password
        old_password = request.POST.get("old_password")
        new_password = request.POST.get("new_password")
        if old_password and new_password:
            is_change, message = change_password(user, old_password, new_password)
            # print(is_change, message)
            if is_change:
                #đăng xuất user tất cả token
                logout_view(request)
                return render(request, "accounts/login.html", {
                    "messages": ["Password updated successfully. Please login again."]
                })
            else:
                return render(request, "accounts/edit_password.html", {
                    "user": user,
                    "profile": profile,
                    "messages": ["Old password is incorrect."]
                })
        return render(request, "accounts/edit_password.html", {
            "user": user,
            "profile": profile,
            "messages": ["Please provide both old and new passwords."]
        })
    except (jwt.ExpiredSignatureError, jwt.DecodeError, User.DoesNotExist):
        return redirect("accounts:login")
    
#View Block User in templates/accounts/block.html
@csrf_exempt
def blocked_users_view(request):
    access_token = request.COOKIES.get("access")
    if not access_token:
        return redirect("accounts:login")

    try:
        payload = jwt.decode(
            access_token,
            settings.SECRET_KEY,
            algorithms=["HS256"]
        )
        current_user_id = payload.get("user_id")
        current_user = User.objects.get(id=current_user_id)
        if getattr(current_user, "is_deleted", False):
            return redirect("accounts:login")
        blocked_users = get_list_blocked_users(current_user)

        return render(request, "accounts/blocked_users.html", {
            "current_user": current_user,
            "blocked_users": blocked_users
        })

    except (jwt.ExpiredSignatureError, jwt.DecodeError, User.DoesNotExist):
        return redirect("accounts:login")
    
@csrf_exempt
def block_user_view(request, user_id):
    access_token = request.COOKIES.get("access")
    if not access_token:
        return redirect("accounts:login")

    try:
        payload = jwt.decode(
            access_token,
            settings.SECRET_KEY,
            algorithms=["HS256"]
        )
        current_user_id = payload.get("user_id")
        current_user = User.objects.get(id=current_user_id)
        if getattr(current_user, "is_deleted", False):
            return redirect("accounts:login")
        target_user = get_object_or_404(User, id=user_id)

        if request.method == "POST":
            block_user(current_user, target_user)
            return redirect("accounts:profile-other", id=target_user.id)

        return render(request, "accounts/blocked_users.html", {
            "current_user": current_user,
            "target_user": target_user
        })

    except (jwt.ExpiredSignatureError, jwt.DecodeError, User.DoesNotExist):
        return redirect("accounts:login")
    
@csrf_exempt
def unblock_user_view(request, user_id):
    access_token = request.COOKIES.get("access")
    if not access_token:
        # Trả về JSON lỗi 401 để file JS bắt được và tự động chuyển về trang đăng nhập
        return JsonResponse({"status": "error", "message": "Unauthorized"}, status=401)

    try:
        payload = jwt.decode(
            access_token,
            settings.SECRET_KEY,
            algorithms=["HS256"]
        )
        current_user_id = payload.get("user_id")
        current_user = User.objects.get(id=current_user_id)
        if getattr(current_user, "is_deleted", False):
            return redirect("accounts:login")
        target_user = get_object_or_404(User, id=user_id)

        if request.method == "POST":
            # Gọi hàm xử lý bỏ chặn trong services[cite: 10, 11]
            unblock_user(current_user, target_user)
            # Trả về JSON báo thành công cho Javascript xử lý ẩn thẻ trên màn hình
            return JsonResponse({"status": "success", "message": "Đã bỏ chặn người dùng"})

        # (Tùy chọn) Nếu lỡ ai đó gõ thẳng link lên thanh địa chỉ (GET request)
        return redirect("accounts:profile", id=target_user.id)

    except (jwt.ExpiredSignatureError, jwt.DecodeError, User.DoesNotExist):
        return JsonResponse({"status": "error", "message": "Unauthorized"}, status=401)
    
@csrf_exempt
def delete_my_account_view(request):
    access_token = request.COOKIES.get("access")
    if not access_token:
        return redirect("accounts:login")

    if request.method != "POST":
        return redirect("accounts:settings")

    try:
        payload = jwt.decode(
            access_token,
            settings.SECRET_KEY,
            algorithms=["HS256"]
        )
        user_id = payload.get("user_id")
        user = User.objects.get(id=user_id)
        if getattr(user, "is_deleted", False):
            return redirect("accounts:login")

        success, message = soft_delete_account(user)
        if not success:
            messages.error(request, message)
            return redirect("accounts:settings")

        response = redirect("accounts:login")
        response.delete_cookie("access")
        response.delete_cookie("refresh")
        return response

    except (jwt.ExpiredSignatureError, jwt.DecodeError, User.DoesNotExist):
        response = redirect("accounts:login")
        response.delete_cookie("access")
        response.delete_cookie("refresh")
        return response
    

@csrf_exempt
def settings_page_view(request):
    access_token = request.COOKIES.get("access")
    if not access_token:
        return redirect("accounts:login")

    try:
        payload = jwt.decode(
            access_token,
            settings.SECRET_KEY,
            algorithms=["HS256"]
        )
        user_id = payload.get("user_id")
        user = User.objects.get(id=user_id)
        if getattr(user, "is_deleted", False):
            return redirect("accounts:login")
        profile = get_object_or_404(UserProfile, user=user)

        return render(request, "accounts/settings.html", {
            "user": user,
            "profile": profile
        })

    except (jwt.ExpiredSignatureError, jwt.DecodeError, User.DoesNotExist):
        return redirect("accounts:login")
