from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.core.mail import send_mail
from django.conf import settings
import jwt
from apps.middleware.utils import generate_jwt_pair_for_user
from django.contrib import messages
from .models import User, PasswordResetToken, EmailVerificationToken, UserProfile
from .services import *
from apps.accounts.services import *
from apps.posts.services import *

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

        reset_url = f"http://127.0.0.1:8080/accounts/reset-password/?token={token.token}"
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
        return redirect("login")

    try:
        payload = jwt.decode(
            access_token,
            settings.SECRET_KEY,
            algorithms=["HS256"]
        )

        current_user_id = payload.get("user_id")
        current_user = User.objects.get(id=current_user_id)

        if id is not None:
            id = int(id)

        # user đang xem
        if id:
            user = get_object_or_404(User, id=id)
        elif username:
            user = get_object_or_404(User, username=username)
        else:
            user = current_user

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
        return redirect("login")

@csrf_exempt
def edit_profile_view(request):
    access_token = request.COOKIES.get("access")
    if not access_token:
        return redirect("login")

    try:
        payload = jwt.decode(
            access_token,
            settings.SECRET_KEY,
            algorithms=["HS256"]
        )
        user_id = payload.get("user_id")
        user = User.objects.get(id=user_id)
        profile = get_object_or_404(UserProfile, user=user)
        print(profile.birth_day)

        if request.method == "GET":
            return render(request, "accounts/edit_profile.html", {
                "user": user,
                "profile": profile
            })

        # POST: cập nhật profile
        # 1. Cập nhật text fields
        full_name = request.POST.get("full_name", profile.full_name)
        bio = request.POST.get("bio", profile.bio)
        address = request.POST.get("address", profile.address)
        town = request.POST.get("town", profile.town)
        province = request.POST.get("province", profile.province)
        nationality = request.POST.get("nationality", profile.nationality)
        school = request.POST.get("school", profile.school)
        phone_number = request.POST.get("phone_number", profile.phone_number)
        birth_day = request.POST.get("birth_day")
        if birth_day:
            profile.birth_day = birth_day  # Django tự parse date string "YYYY-MM-DD"
        print(profile.birth_day)
        print(birth_day)
        # 2. Cập nhật avatar nếu có upload
        avatar = request.FILES.get("avatar")
        if avatar:
            profile.avatar = avatar

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
        return redirect("login")

@csrf_exempt
def update_email_view(request):
    access_token = request.COOKIES.get("access")
    if not access_token:
        return redirect("login")

    try:
        payload = jwt.decode(
            access_token,
            settings.SECRET_KEY,
            algorithms=["HS256"]
        )
        user_id = payload.get("user_id")
        user = User.objects.get(id=user_id)
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
        return redirect("login")
    
@csrf_exempt
def update_username_view(request):
    access_token = request.COOKIES.get("access")
    if not access_token:
        return redirect("login")

    try:
        payload = jwt.decode(
            access_token,
            settings.SECRET_KEY,
            algorithms=["HS256"]
        )
        user_id = payload.get("user_id")
        user = User.objects.get(id=user_id)
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
        return redirect("login")
    
@csrf_exempt
def update_password_view(request):
    access_token = request.COOKIES.get("access")
    if not access_token:
        return redirect("login")

    try:
        payload = jwt.decode(
            access_token,
            settings.SECRET_KEY,
            algorithms=["HS256"]
        )
        user_id = payload.get("user_id")
        user = User.objects.get(id=user_id)
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
        return redirect("login")