# Generated manually for post attachments support.

import apps.posts.models
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posts", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="PostAttachment",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "attachment_type",
                    models.CharField(
                        choices=[("image", "Image"), ("audio", "Audio"), ("file", "File")],
                        max_length=16,
                    ),
                ),
                ("file", models.FileField(upload_to=apps.posts.models._post_attachment_upload_to)),
                ("original_name", models.CharField(max_length=255)),
                ("content_type", models.CharField(blank=True, max_length=128)),
                ("size_bytes", models.PositiveBigIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "post",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="attachments",
                        to="posts.post",
                    ),
                ),
            ],
            options={
                "ordering": ["created_at"],
                "indexes": [
                    models.Index(fields=["post", "created_at"], name="post_attach_post_created_idx"),
                    models.Index(fields=["post", "attachment_type"], name="post_attach_type_idx"),
                ],
            },
        ),
    ]
