import enum
from typing import Self


class Intents(enum.IntFlag):
    """
    A set of event types that the client can ask to be received when
    identifying with the gateway.

    .. seealso:: https://discord.com/developers/docs/topics/gateway#gateway-intents

    """

    GUILDS = 1 << 0
    """Corresponds with the following events:

    - GUILD_CREATE
    - GUILD_UPDATE
    - GUILD_DELETE
    - GUILD_ROLE_CREATE
    - GUILD_ROLE_UPDATE
    - GUILD_ROLE_DELETE
    - CHANNEL_CREATE
    - CHANNEL_UPDATE
    - CHANNEL_DELETE
    - CHANNEL_PINS_UPDATE
    - THREAD_CREATE
    - THREAD_UPDATE
    - THREAD_DELETE
    - THREAD_LIST_SYNC
    - THREAD_MEMBER_UPDATE
    - THREAD_MEMBERS_UPDATE *
    - STAGE_INSTANCE_CREATE
    - STAGE_INSTANCE_UPDATE
    - STAGE_INSTANCE_DELETE

    """
    GUILD_MEMBERS = 1 << 1
    """Corresponds with the following events:

    - GUILD_MEMBER_ADD
    - GUILD_MEMBER_UPDATE
    - GUILD_MEMBER_REMOVE
    - THREAD_MEMBERS_UPDATE *

    """
    GUILD_MODERATION = 1 << 2
    """Corresponds with the following events:

    - GUILD_AUDIT_LOG_ENTRY_CREATE
    - GUILD_BAN_ADD
    - GUILD_BAN_REMOVE

    """
    GUILD_EMOJIS_AND_STICKERS = 1 << 3
    """Corresponds with the following events:

    - GUILD_EMOJIS_UPDATE
    - GUILD_STICKERS_UPDATE

    """
    GUILD_INTEGRATIONS = 1 << 4
    """Corresponds with the following events:

    - GUILD_INTEGRATIONS_UPDATE
    - INTEGRATION_CREATE
    - INTEGRATION_UPDATE
    - INTEGRATION_DELETE

    """
    GUILD_WEBHOOKS = 1 << 5
    """Corresponds with the following events:

    - WEBHOOKS_UPDATE

    """
    GUILD_INVITES = 1 << 6
    """Corresponds with the following events:

    - INVITE_CREATE
    - INVITE_DELETE

    """
    GUILD_VOICE_STATES = 1 << 7
    """Corresponds with the following events:

    - VOICE_STATE_UPDATE

    """
    GUILD_PRESENCES = 1 << 8
    """Corresponds with the following events:

    - PRESENCE_UPDATE

    """
    GUILD_MESSAGES = 1 << 9
    """Corresponds with the following events:

    - MESSAGE_CREATE
    - MESSAGE_UPDATE
    - MESSAGE_DELETE
    - MESSAGE_DELETE_BULK

    """
    GUILD_MESSAGE_REACTIONS = 1 << 10
    """Corresponds with the following events:

    - MESSAGE_REACTION_ADD
    - MESSAGE_REACTION_REMOVE
    - MESSAGE_REACTION_REMOVE_ALL
    - MESSAGE_REACTION_REMOVE_EMOJI

    """
    GUILD_MESSAGE_TYPING = 1 << 11
    """Corresponds with the following events:

    - TYPING_START

    """
    DIRECT_MESSAGES = 1 << 12
    """Corresponds with the following events:

    - MESSAGE_CREATE
    - MESSAGE_UPDATE
    - MESSAGE_DELETE
    - CHANNEL_PINS_UPDATE

    """
    DIRECT_MESSAGE_REACTIONS = 1 << 13
    """Corresponds with the following events:

    - MESSAGE_REACTION_ADD
    - MESSAGE_REACTION_REMOVE
    - MESSAGE_REACTION_REMOVE_ALL
    - MESSAGE_REACTION_REMOVE_EMOJI

    """
    DIRECT_MESSAGE_TYPING = 1 << 14
    """Corresponds with the following events:

    - TYPING_START

    """
    MESSAGE_CONTENT = 1 << 15
    """Provides data for events that contain message content fields.

    .. seealso:: https://discord.com/developers/docs/topics/gateway#message-content-intent

    """
    GUILD_SCHEDULED_EVENTS = 1 << 16
    """Corresponds with the following events:

    - GUILD_SCHEDULED_EVENT_CREATE
    - GUILD_SCHEDULED_EVENT_UPDATE
    - GUILD_SCHEDULED_EVENT_DELETE
    - GUILD_SCHEDULED_EVENT_USER_ADD
    - GUILD_SCHEDULED_EVENT_USER_REMOVE

    """
    AUTO_MODERATION_CONFIGURATION = 1 << 20
    """Corresponds with the following events:

    - AUTO_MODERATION_RULE_CREATE
    - AUTO_MODERATION_RULE_UPDATE
    - AUTO_MODERATION_RULE_DELETE

    """
    AUTO_MODERATION_EXECUTION = 1 << 21
    """Corresponds with the following events:

    - AUTO_MODERATION_ACTION_EXECUTION

    """

    @classmethod
    def all(cls) -> Self:
        """Returns a flag with all intents enabled."""
        return cls(-1)

    @classmethod
    def privileged(cls) -> Self:
        """Returns a flag with all privileged intents enabled."""
        # fmt: off
        return (
            Intents.GUILD_PRESENCES
            | Intents.GUILD_MEMBERS
            | Intents.MESSAGE_CONTENT
        )
        # fmt: on

    @classmethod
    def standard(cls) -> Self:
        """Returns a flag with all standard intents enabled."""
        flag = cls.all()
        flag &= ~cls.privileged()
        return flag
