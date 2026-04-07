"""Constants for posts/comment/reaction domain."""

REACTION_CHOICES = (
    ("like", "Like"),
    ("love", "Love"),
    ("haha", "Haha"),
    ("wow", "Wow"),
    ("sad", "Sad"),
    ("angry", "Angry"),
)

REACTION_VALUES = [choice[0] for choice in REACTION_CHOICES]

POST_ATTACHMENT_TYPE_IMAGE = "image"
POST_ATTACHMENT_TYPE_AUDIO = "audio"
POST_ATTACHMENT_TYPE_FILE = "file"

POST_ATTACHMENT_TYPE_CHOICES = (
    (POST_ATTACHMENT_TYPE_IMAGE, "Image"),
    (POST_ATTACHMENT_TYPE_AUDIO, "Audio"),
    (POST_ATTACHMENT_TYPE_FILE, "File"),
)
