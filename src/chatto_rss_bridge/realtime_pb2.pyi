from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class _RealtimeInitialState:
    REALTIME_INITIAL_STATE_UNSPECIFIED: int
    REALTIME_INITIAL_STATE_LIVE_ONLY: int
    REALTIME_INITIAL_STATE_SNAPSHOT: int

class _RealtimeRecovery:
    REALTIME_RECOVERY_UNSPECIFIED: int
    REALTIME_RECOVERY_RESUMED: int
    REALTIME_RECOVERY_SNAPSHOT: int
    REALTIME_RECOVERY_LIVE_ONLY: int

class _RealtimeCloseCode:
    REALTIME_CLOSE_CODE_UNSPECIFIED: int
    REALTIME_CLOSE_CODE_INVALID_REQUEST: int
    REALTIME_CLOSE_CODE_UNSUPPORTED_PROTOCOL: int
    REALTIME_CLOSE_CODE_TEMPORARILY_UNAVAILABLE: int
    REALTIME_CLOSE_CODE_AUTHENTICATION_REQUIRED: int
    REALTIME_CLOSE_CODE_SESSION_RENEWAL_REQUIRED: int
    REALTIME_CLOSE_CODE_RESYNC_REQUIRED: int
    REALTIME_CLOSE_CODE_SESSION_TERMINATED: int
    REALTIME_CLOSE_CODE_PRIVILEGED_MODE_EXPIRED: int

RealtimeInitialState: _RealtimeInitialState
RealtimeRecovery: _RealtimeRecovery
RealtimeCloseCode: _RealtimeCloseCode
REALTIME_INITIAL_STATE_UNSPECIFIED: int
REALTIME_INITIAL_STATE_LIVE_ONLY: int
REALTIME_INITIAL_STATE_SNAPSHOT: int
REALTIME_RECOVERY_UNSPECIFIED: int
REALTIME_RECOVERY_RESUMED: int
REALTIME_RECOVERY_SNAPSHOT: int
REALTIME_RECOVERY_LIVE_ONLY: int
REALTIME_CLOSE_CODE_UNSPECIFIED: int
REALTIME_CLOSE_CODE_INVALID_REQUEST: int
REALTIME_CLOSE_CODE_UNSUPPORTED_PROTOCOL: int
REALTIME_CLOSE_CODE_TEMPORARILY_UNAVAILABLE: int
REALTIME_CLOSE_CODE_AUTHENTICATION_REQUIRED: int
REALTIME_CLOSE_CODE_SESSION_RENEWAL_REQUIRED: int
REALTIME_CLOSE_CODE_RESYNC_REQUIRED: int
REALTIME_CLOSE_CODE_SESSION_TERMINATED: int
REALTIME_CLOSE_CODE_PRIVILEGED_MODE_EXPIRED: int

class RealtimeSubscribe(_message.Message):
    __slots__ = ("protocol_version", "bearer_token", "resume_cursor", "initial_state")
    PROTOCOL_VERSION_FIELD_NUMBER: _ClassVar[int]
    BEARER_TOKEN_FIELD_NUMBER: _ClassVar[int]
    RESUME_CURSOR_FIELD_NUMBER: _ClassVar[int]
    INITIAL_STATE_FIELD_NUMBER: _ClassVar[int]
    protocol_version: int
    bearer_token: str
    resume_cursor: str
    initial_state: int
    def __init__(self, protocol_version: _Optional[int] = ..., bearer_token: _Optional[str] = ..., resume_cursor: _Optional[str] = ..., initial_state: _Optional[int] = ...) -> None: ...

class RealtimeServerFrame(_message.Message):
    __slots__ = ("event", "heartbeat", "close", "caught_up")
    EVENT_FIELD_NUMBER: _ClassVar[int]
    HEARTBEAT_FIELD_NUMBER: _ClassVar[int]
    CLOSE_FIELD_NUMBER: _ClassVar[int]
    CAUGHT_UP_FIELD_NUMBER: _ClassVar[int]
    event: RealtimeEvent
    heartbeat: RealtimeHeartbeat
    close: RealtimeClose
    caught_up: RealtimeCaughtUp
    def __init__(self, event: _Optional[_Union[RealtimeEvent, _Mapping]] = ..., heartbeat: _Optional[_Union[RealtimeHeartbeat, _Mapping]] = ..., close: _Optional[_Union[RealtimeClose, _Mapping]] = ..., caught_up: _Optional[_Union[RealtimeCaughtUp, _Mapping]] = ...) -> None: ...

class RealtimeEvent(_message.Message):
    __slots__ = ("id", "actor_id", "cursor", "message_posted")
    ID_FIELD_NUMBER: _ClassVar[int]
    ACTOR_ID_FIELD_NUMBER: _ClassVar[int]
    CURSOR_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_POSTED_FIELD_NUMBER: _ClassVar[int]
    id: str
    actor_id: str
    cursor: str
    message_posted: MessagePostedEvent
    def __init__(self, id: _Optional[str] = ..., actor_id: _Optional[str] = ..., cursor: _Optional[str] = ..., message_posted: _Optional[_Union[MessagePostedEvent, _Mapping]] = ...) -> None: ...

class MessagePostedEvent(_message.Message):
    __slots__ = ("room_id", "in_reply_to", "thread_root_event_id", "echo_of_event_id", "mentions", "body_plaintext")
    ROOM_ID_FIELD_NUMBER: _ClassVar[int]
    IN_REPLY_TO_FIELD_NUMBER: _ClassVar[int]
    THREAD_ROOT_EVENT_ID_FIELD_NUMBER: _ClassVar[int]
    ECHO_OF_EVENT_ID_FIELD_NUMBER: _ClassVar[int]
    MENTIONS_FIELD_NUMBER: _ClassVar[int]
    BODY_PLAINTEXT_FIELD_NUMBER: _ClassVar[int]
    room_id: str
    in_reply_to: str
    thread_root_event_id: str
    echo_of_event_id: str
    mentions: _containers.RepeatedCompositeFieldContainer[MessageMention]
    body_plaintext: str
    def __init__(self, room_id: _Optional[str] = ..., in_reply_to: _Optional[str] = ..., thread_root_event_id: _Optional[str] = ..., echo_of_event_id: _Optional[str] = ..., mentions: _Optional[_Iterable[_Union[MessageMention, _Mapping]]] = ..., body_plaintext: _Optional[str] = ...) -> None: ...

class MessageMention(_message.Message):
    __slots__ = ("direct", "includes_viewer")
    DIRECT_FIELD_NUMBER: _ClassVar[int]
    INCLUDES_VIEWER_FIELD_NUMBER: _ClassVar[int]
    direct: DirectUserMention
    includes_viewer: bool
    def __init__(self, direct: _Optional[_Union[DirectUserMention, _Mapping]] = ..., includes_viewer: _Optional[bool] = ...) -> None: ...

class DirectUserMention(_message.Message):
    __slots__ = ("user_id",)
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    def __init__(self, user_id: _Optional[str] = ...) -> None: ...

class RealtimeHeartbeat(_message.Message):
    __slots__ = ("cursor",)
    CURSOR_FIELD_NUMBER: _ClassVar[int]
    cursor: str
    def __init__(self, cursor: _Optional[str] = ...) -> None: ...

class RealtimeCaughtUp(_message.Message):
    __slots__ = ("cursor", "recovery")
    CURSOR_FIELD_NUMBER: _ClassVar[int]
    RECOVERY_FIELD_NUMBER: _ClassVar[int]
    cursor: str
    recovery: int
    def __init__(self, cursor: _Optional[str] = ..., recovery: _Optional[int] = ...) -> None: ...

class RealtimeClose(_message.Message):
    __slots__ = ("code", "message", "reconnect", "retry_after")
    CODE_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    RECONNECT_FIELD_NUMBER: _ClassVar[int]
    RETRY_AFTER_FIELD_NUMBER: _ClassVar[int]
    code: int
    message: str
    reconnect: bool
    retry_after: RealtimeRetryAfter
    def __init__(self, code: _Optional[int] = ..., message: _Optional[str] = ..., reconnect: _Optional[bool] = ..., retry_after: _Optional[_Union[RealtimeRetryAfter, _Mapping]] = ...) -> None: ...

class RealtimeRetryAfter(_message.Message):
    __slots__ = ("seconds", "nanos")
    SECONDS_FIELD_NUMBER: _ClassVar[int]
    NANOS_FIELD_NUMBER: _ClassVar[int]
    seconds: int
    nanos: int
    def __init__(self, seconds: _Optional[int] = ..., nanos: _Optional[int] = ...) -> None: ...
