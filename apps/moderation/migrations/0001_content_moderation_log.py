from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="ContentModerationLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("target_type", models.CharField(choices=[("post", "Post"), ("comment", "Comment"), ("post_image", "Post Image"), ("comment_image", "Comment Image"), ("post_file", "Post File"), ("comment_file", "Comment File"), ("hashtag", "Hashtag")], max_length=20)),
                ("target_id", models.PositiveIntegerField()),
                ("action", models.CharField(choices=[("flag", "Flag"), ("unflag", "Unflag"), ("hide", "Hide"), ("restore", "Restore"), ("delete", "Delete"), ("update", "Update")], max_length=20)),
                ("reason", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="accounts.user")),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="contentmoderationlog",
            index=models.Index(fields=["target_type", "target_id"], name="moderation_content_target_idx"),
        ),
        migrations.AddIndex(
            model_name="contentmoderationlog",
            index=models.Index(fields=["created_at"], name="moderation_content_created_idx"),
        ),
    ]
