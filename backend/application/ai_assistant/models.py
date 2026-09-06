"""Django models for AI assistant memory."""

from django.conf import settings
from django.db import models


class AssistantMemoryScope(models.Model):
    """User-scoped memory stream.

    ``scope_key`` deliberately sits behind a resolver in ``memory_service``.
    The first rollout keeps one scope per user, while leaving a safe extension
    point for project/conversation scopes later.
    """

    scope_key = models.CharField(max_length=180, unique=True, db_index=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="ai_memory_scopes",
    )
    slots = models.JSONField(default=dict, blank=True)
    summary = models.TextField(blank=True, default="")
    summary_through_sequence = models.PositiveBigIntegerField(default=0)
    summary_revision = models.PositiveIntegerField(default=0)
    revision = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ai_assistant_memory_scope"
        indexes = [
            models.Index(fields=["owner", "updated_at"]),
        ]

    def __str__(self):
        return self.scope_key


class AssistantMemoryMessage(models.Model):
    """A persisted human or assistant turn in a memory scope."""

    ROLE_HUMAN = "human"
    ROLE_AI = "ai"
    ROLE_CHOICES = (
        (ROLE_HUMAN, "Human"),
        (ROLE_AI, "Assistant"),
    )

    scope = models.ForeignKey(
        AssistantMemoryScope,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    sequence = models.PositiveBigIntegerField()
    role = models.CharField(max_length=12, choices=ROLE_CHOICES)
    content = models.TextField()
    token_count = models.PositiveIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)
    legacy_message_id = models.PositiveBigIntegerField(null=True, blank=True, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ai_assistant_memory_message"
        constraints = [
            models.UniqueConstraint(
                fields=["scope", "sequence"],
                name="ai_memory_scope_sequence_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["scope", "sequence"]),
            models.Index(fields=["scope", "created_at"]),
        ]

    def __str__(self):
        return f"{self.scope.scope_key}:{self.sequence}:{self.role}"
