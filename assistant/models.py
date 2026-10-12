from django.db import models


class ChatMessage(models.Model):
    session_id = models.CharField(max_length=200, db_index=True)
    dealer_id = models.IntegerField(null=True, blank=True)
    role = models.CharField(max_length=10)  # "user" | "assistant"
    content = models.TextField()
    cited_skus = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
