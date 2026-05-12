from django.db import models

class SystemConfig(models.Model):
    CONFIG_TYPES = (
        ('int', 'Số nguyên (Limit)'),
        ('bool', 'Bật/Tắt (Toggle)'),
        ('string', 'Văn bản'),
    )
    key = models.CharField(max_length=100, unique=True, help_text="Ví dụ: MAX_UPLOAD_MB, ENABLE_REGISTRATION")
    value = models.CharField(max_length=255)
    description = models.CharField(max_length=255, blank=True)
    data_type = models.CharField(max_length=20, choices=CONFIG_TYPES, default='string')
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.key}: {self.value}"