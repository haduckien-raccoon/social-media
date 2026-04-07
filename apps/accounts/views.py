from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.core.mail import send_mail
from django.conf import settings

from .models import User, PasswordResetToken
from .services import (
    register_user,
    login_user,
    create_jwt_pair_for_user,
    logout_user,
    create_password_reset_token,
    reset_user_password,
)

@csrf_exempt
def register_view(request):
    """GET: hiển thị form đăng ký. POST: tạo tài khoản mới.

    Input: POST fields username, email, password.
    Output: render template với message thành công hoặc lỗi.
    """
    if request.method == "GET":
        return render(request, "accounts/register.html")

    username = request.POST.get("username", "").strip()
    email = request.POST.get("email", "").strip()
    password = request.POST.get("password", "")

    if not username or not email or not password:
        return render(request, "accounts/register.html", {
            "error": "All fields are required"
        })

    try:
        user, error = register_user(username, email, password)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("register_view_unexpected_error")
        return render(request, "accounts/register.html", {
            "error": "An unexpected error occurred. Please try again."
        })

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

    response = redirect("login")
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

        reset_url = f"{settings.APP_PUBLIC_BASE_URL}/accounts/reset-password/?token={token.token}"
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
        token = EmailVerificationToken.objects.get(
            token=token_value,
            is_used=False
        )
    except EmailVerificationToken.DoesNotExist:
        return render(request, "accounts/verify_email.html", {
            "error": "Token is invalid or already used."
        })

    if token.expires_at < timezone.now():
        return render(request, "accounts/verify_email.html", {
            "error": "Verification token has expired."
        })
    
    user = token.user
    user.is_active = True
    user.save()

    token.is_used = True
    token.save()

    return render(request, "accounts/verify_email.html", {
        "message": "Email verified successfully. You can login now."
    })
