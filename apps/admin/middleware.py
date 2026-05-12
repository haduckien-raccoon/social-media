# apps/admin/middleware.py
import logging
import time

access_logger = logging.getLogger('system_access')
error_logger = logging.getLogger('django.request')

class SystemLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start_time = time.time()
        
        # Xử lý request và lấy response
        response = self.get_response(request)
        
        duration = time.time() - start_time
        ip = self.get_client_ip(request)
        user = request.user.username if request.user.is_authenticated else "Anonymous"

        # Bỏ qua không log các request lấy file tĩnh tĩnh (CSS/JS/Images) để tránh rác log
        if not request.path.startswith('/static/') and not request.path.startswith('/media/'):
            log_msg = f"IP: {ip:<15} | User: {user:<15} | Method: {request.method:<5} | Status: {response.status_code} | Duration: {duration:.3f}s | Path: {request.path}"
            
            # Ghi vào access.log
            access_logger.info(log_msg)

            # Nếu là lỗi 5xx nhưng chưa bị bắt, ghi thêm vào error.log
            if response.status_code >= 500:
                error_logger.error(f"SERVER ERROR {response.status_code}: {log_msg}")

        return response

    def process_exception(self, request, exception):
        """Tự động bắt mọi lỗi (Exception) xảy ra trong hệ thống và ghi vào error.log"""
        ip = self.get_client_ip(request)
        error_logger.error(f"EXCEPTION at {request.path} (IP: {ip}): {str(exception)}", exc_info=True)

    def get_client_ip(self, request):
        """Hàm lấy IP thực của user (ngay cả khi qua Nginx/Proxy)"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0]
        return request.META.get('REMOTE_ADDR')