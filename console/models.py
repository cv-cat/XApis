from typing import Literal
import secrets
from pydantic import BaseModel, Field, ConfigDict, field_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Credentials(Model):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[a-zA-Z0-9_.@-]+$")
    password: str = Field(min_length=12, max_length=128)

    @field_validator("password", mode="before")
    @classmethod
    def preserve_password(cls, v):
        return v

    model_config = ConfigDict(extra="forbid")


class Setup(Credentials):
    token: str = Field(min_length=16, max_length=256)


class LoginCredentials(Credentials):
    # Authenticate existing hashes; creation rules belong to setup/password forms.
    password: str = Field(min_length=1, max_length=128)


class UserCreate(Credentials):
    role: Literal["admin", "member"] = "member"


class UserUpdate(Model):
    disabled: bool = False
    role: Literal["admin", "member"] = "member"


class Password(Model):
    current: str = Field(min_length=1, max_length=128)
    new: str = Field(min_length=12, max_length=128)
    model_config = ConfigDict(extra="forbid")


class AccountCreate(Model):
    name: str = Field(min_length=1, max_length=80)
    proxy: str = Field(min_length=8, max_length=1000)
    warmup_days: int = Field(default=4, ge=1, le=90)


class KeywordGroup(Model):
    name: str = Field(min_length=1, max_length=100)
    keywords: list[str] = Field(min_length=1, max_length=100)


class Maintenance(Model):
    group_ids: list[str] = Field(default_factory=list, max_length=20)
    enabled: bool = True
    interval_minutes: int = Field(default=60, ge=15, le=1440)
    pages_per_cycle: int = Field(default=3, ge=1, le=10)
    read_home: bool = True
    home_pages_per_cycle: int = Field(default=2, ge=1, le=10)
    delay_min_seconds: int = Field(default=30, ge=5, le=600)
    delay_max_seconds: int = Field(default=90, ge=5, le=1800)
    read_comments: bool = True
    comment_pages: int = Field(default=2, ge=1, le=5)


class Proxy(Model):
    proxy: str = Field(min_length=8, max_length=1000)


class LoginAccount(Model):
    username: str = Field(default="", max_length=100)
    password: str = Field(default="", max_length=256)
    cookies: str = Field(default="", max_length=20000)
    profile: dict | list | None = None
    model_config = ConfigDict(extra="forbid")


class ChatRelay(Model):
    context_id: str = Field(min_length=20, max_length=100)
    url: str = Field(min_length=8, max_length=500)
    method: Literal["GET", "POST"]
    headers: dict[str, str] = Field(default_factory=dict, max_length=10)
    body: str = Field(default="", max_length=1_400_000)


class ChatPassword(Model):
    pin: str = Field(min_length=4, max_length=128)
    model_config = ConfigDict(extra="forbid")


class ChatSend(Model):
    conversation_id: str = Field(min_length=1, max_length=200, pattern=r"^[a-zA-Z0-9:-]+$")
    message_id: str = Field(pattern=r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
    encoded_message_create_event: str = Field(min_length=4, max_length=100_000, pattern=r"^[A-Za-z0-9+/]+={0,2}$")
    encoded_message_event_signature: str = Field(min_length=4, max_length=10_000, pattern=r"^[A-Za-z0-9+/]+={0,2}$")


class ChatParticipantKey(Model):
    user_id: str = Field(pattern=r"^[0-9]{1,30}$")
    public_key_version: str = Field(pattern=r"^[0-9]{1,30}$")
    encrypted_conversation_key: str = Field(min_length=4, max_length=10_000, pattern=r"^[A-Za-z0-9+/]+={0,2}$")


class ChatSignature(Model):
    signing_public_key: str = Field(min_length=4, max_length=1000, pattern=r"^[A-Za-z0-9+/]+={0,2}$")
    public_key_version: str = Field(pattern=r"^[0-9]{1,30}$")
    signature_version: str = Field(pattern=r"^[0-9]{1,10}$")
    signature: str = Field(min_length=4, max_length=1000, pattern=r"^[A-Za-z0-9+/]+={0,2}$")


class ChatKeyAction(Model):
    message_id: str = Field(pattern=r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
    encoded_message_event_detail: str = Field(min_length=4, max_length=100_000, pattern=r"^[A-Za-z0-9+/]+={0,2}$")
    message_event_signature: ChatSignature


class ChatKeySetup(Model):
    conversation_id: str = Field(pattern=r"^[0-9]{1,30}:[0-9]{1,30}$")
    conversation_key_version: str = Field(pattern=r"^[0-9]{1,30}$")
    conversation_participant_keys: list[ChatParticipantKey] = Field(min_length=1, max_length=2)
    action_signatures: list[ChatKeyAction] = Field(min_length=1, max_length=1)


class AIConfig(Model):
    base_url: str = Field(min_length=8, max_length=500)
    model: str = Field(min_length=1, max_length=100)
    api_key: str = Field(default="", max_length=1000)
    instruction: str = Field(default="", max_length=2000)
    token_parameter: Literal["auto", "max_tokens", "max_completion_tokens"] = "auto"


class Generate(Model):
    prompt: str = Field(min_length=1, max_length=4000)
    entry_ids: list[str] = Field(default_factory=list, max_length=5)
    style: str = Field(default="清晰、有观点，适合 X 的中文贴文", max_length=500)
    long: bool = False


class Source(Model):
    name: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=8, max_length=1000)
    kind: Literal["rss", "web"] = "rss"
    enabled: bool = True


class Rule(Model):
    name: str = Field(min_length=1, max_length=100)
    account_id: str
    source_ids: list[str] = Field(min_length=1, max_length=10)
    prompt: str = Field(min_length=1, max_length=4000)
    mode: Literal["draft", "publish"] = "draft"
    interval_minutes: int = Field(default=180, ge=15, le=43200)
    daily_limit: int = Field(default=3, ge=1, le=24)
    enabled: bool = False


class Payload(Model):
    kind: Literal["post", "thread", "article"] = "post"
    text: str = Field(default="", max_length=25000)
    texts: list[str] = Field(default_factory=list, max_length=25)
    title: str = Field(default="", max_length=250)
    media: list[str] = Field(default_factory=list, max_length=4)
    reply_to: str = Field(default="", max_length=200)
    quote_url: str = Field(default="", max_length=300)
    long: bool = False
    article_id: str = Field(default="", max_length=100)
    publish_article: bool = False
    caption: str = Field(default="", max_length=1000)
    reply_mode: Literal["", "All", "Community", "Verified", "ByInvitation"] = ""
    sources: list[dict] = Field(default_factory=list, max_length=5)


class Job(Model):
    account_id: str
    request_id: str = Field(min_length=16, max_length=100)
    payload: Payload
    state: Literal["draft", "queued"] = "draft"
    scheduled: float | None = None


class Action(Model):
    action: Literal[
        "like",
        "unlike",
        "repost",
        "unrepost",
        "bookmark",
        "unbookmark",
        "delete",
        "follow",
        "unfollow",
    ]
    target: str = Field(min_length=1, max_length=250)


class Explorer(Model):
    operation: str
    params: dict = Field(default_factory=dict)


class ArticleAction(Model):
    action: Literal["delete", "publish"]
    article_id: str = Field(pattern=r"^\d+$")
    caption: str = Field(default="", max_length=1000)
    request_id: str = Field(
        default_factory=lambda: secrets.token_hex(16), min_length=16, max_length=60
    )
