import asyncio
import inspect
import logging
import sys
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable, cast

import websockets.client
import websockets.frames
from websockets.client import WebSocketClientProtocol
from websockets.exceptions import ConnectionClosed

from .backoff import Backoff, ExponentialBackoff
from .constants import (
    GATEWAY_CANNOT_RESUME_CLOSE_CODES,
    GATEWAY_CLOSE_CODES,
    GATEWAY_RECONNECT_CLOSE_CODES,
    WEBSOCKET_CLOSE_CODES,
)
from .errors import _unwrap_first_exception
from .events import DispatchEvent, Event, Hello, InvalidSession
from .heartbeat import Heart
from .stream import PlainTextStream, Stream, ZLibStream
from discord_ws import constants
from discord_ws.errors import (
    AuthenticationFailedError,
    ConnectionClosedError,
    GatewayInterrupt,
    GatewayReconnect,
    HeartbeatLostError,
    PrivilegedIntentsError,
    SessionInvalidated,
)
from discord_ws.http import _create_user_agent
from discord_ws.intents import Intents
from discord_ws.metadata import get_distribution_metadata
from discord_ws.types import GatewayPresenceUpdate
from user_agents import parse

log = logging.getLogger(__name__)

DispatchFunc = Callable[[DispatchEvent], Any]


def parse_user_agent(user_agent_string):
    # Parse the user agent string using the user_agents library
    user_agent = parse(user_agent_string)

    # Extracting properties from the user agent
    browser_group = user_agent.browser.family
    browser_version = user_agent.browser.version_string
    os_name = user_agent.os.family

    return {
        "browser": browser_group,
        "browser_version": browser_version,
        "os": os_name,
    }

class Client:
    """The websocket client for connecting to the Discord Gateway."""

    gateway_url: str | None
    """
    The URL to use when connecting to the gateway.

    If this is not provided, it will automatically be fetched
    from the Get Gateway HTTP endpoint during :meth:`Client.run()`.

    """

    token: str
    """The token to use for authenticating with the gateway."""

    intents: Intents
    """The gateway intents to use when identifying with the gateway."""

    user_agent: str
    """The user agent used when connecting to the gateway."""

    compress: bool
    """
    If true, zlib transport compression will be enabled for data received
    by Discord.

    This is distinct from payload compression which is not implemented
    by this library.

    """

    large_threshold: int | None
    """
    The threshold where offline guild members are no longer sent,
    provided when identifying with the gateway.
    """

    presence: GatewayPresenceUpdate | None
    """The presence for the client to use when identifying to the gateway."""

    _dispatch_func: DispatchFunc | None
    """The function to call when a dispatch event is received.

    This is set by :meth:`on_dispatch()`.

    """

    _heart: Heart
    """The heart used for maintaining heartbeats across connections."""

    _reconnect_backoff: Backoff
    """The backoff function used when reconnecting to Discord."""

    _stream: Stream | None
    """The stream object used for sending and receiving with the current connection.

    This is set by :meth:`_create_stream()`.

    """

    _current_websocket: WebSocketClientProtocol | None
    """
    The current connection to the Discord gateway, if any.

    This attribute should not be used directly; see the :attr:`_ws` property.

    """

    _resume_gateway_url: str | None
    """
    The URL to use when resuming gateway connections.

    This is provided during the Ready gateway event.

    """

    _session_id: str | None
    """
    The session ID to use when resuming gateway connections.

    This is provided during the Ready gateway event.

    """

    _dispatch_futures: set[asyncio.Future]
    """A set of any future-like objects returned by :attr:`_dispatch_func`.

    This set only exists to maintain a strong reference to each future.
    Once a future is completed, it is automatically removed from the set.

    """

    def __init__(
            self,
            *,
            token: str,
            intents: Intents,
            gateway_url: str | None = None,
            user_agent: str | None = None,
            compress: bool = True,
            large_threshold: int | None = None,
            presence: GatewayPresenceUpdate | None = None,
    ) -> None:
        """
        :param token:
            The token to use for authenticating with the gateway.
        :param intents:
            The gateway intents to use when identifying with the gateway.
        :param gateway_url:
            The URL to use when connecting to the gateway.
            If this is not provided, it will automatically be fetched
            from the Get Gateway HTTP endpoint during :meth:`Client.run()`.
        :param user_agent:
            An optional user agent used when connecting to the gateway,
            overriding the library's default.
        :param compress:
            If true, zlib transport compression will be enabled for data received
            by Discord. This is distinct from payload compression which is not
            implemented by this library.
        :param large_threshold:
            The threshold where offline guild members are no longer sent,
            provided when identifying with the gateway.
        :param presence:
            An optional presence for the client to use when identifying
            to the gateway.

        """
        if user_agent is None:
            user_agent = _create_user_agent(get_distribution_metadata())

        self.gateway_url = gateway_url
        self.token = token
        self.intents = intents
        self.user_agent = user_agent
        self.compress = compress
        self.large_threshold = large_threshold
        self.presence = presence

        self._dispatch_func = None
        self._heart = Heart(token)
        self._reconnect_backoff = ExponentialBackoff()
        self._stream = None

        self._current_websocket = None
        self._resume_gateway_url = None
        self._session_id = None
        self._dispatch_futures = set()

    def on_dispatch(self, func: DispatchFunc | None) -> DispatchFunc | None:
        """Sets the callback function to invoke when an event is dispatched.

        This can be a coroutine function or return an awaitable object.

        """
        self._dispatch_func = func
        return func

    async def run(self, *, reconnect: bool = True) -> None:
        """Begins and maintains a connection to the gateway.

        Use the :meth:`close()` method to gracefully close the connection.

        This method may raise an :class:`ExceptionGroup` so it is
        recommended to handle errors using ``except*`` syntax.

        :param reconnect:
            If True, this method will reconnect to Discord
            where possible.
        :raises GatewayReconnect:
            The gateway has asked us to reconnect.
            Only raised when reconnect is False.
        :raises HeartbeatLostError:
            The gateway failed to acknowledge our heartbeat.
            Only raised when reconnect is False.
        :raises SessionInvalidated:
            The gateway has invalidated our session.
            Only raised when reconnect is False.

        """
        if self.gateway_url is None:
            self.gateway_url = await self._get_gateway_url()

        first_connect = True
        while first_connect or reconnect:
            first_connect = False

            if self._can_resume():
                gateway_url = cast(str, self._resume_gateway_url)
                session_id = cast(str, self._session_id)
            else:
                gateway_url = self.gateway_url
                session_id = None
                self._heart.sequence = None

            log.info("Connecting to the gateway (session_id: %s) %s", session_id, self.token[:10])

            try:
                async with self._connect(gateway_url) as ws:
                    await self._handle_connection(session_id=session_id)
            except* ConnectionClosed as eg:
                # Multiple errors should still be from the same connection,
                # so we're only interested in handling the first occurrence
                e = _unwrap_first_exception(eg)
                assert e is not None
                reconnect = self._handle_connection_closed(e) and reconnect
            except* (GatewayInterrupt, HeartbeatLostError):
                if not reconnect:
                    raise

            if reconnect:
                duration = self._reconnect_backoff()
                log.info("Waiting %.3fs before reconnecting %s", duration, self.token[:10])
                await asyncio.sleep(duration)

    async def set_presence(
            self,
            presence: GatewayPresenceUpdate,
            *,
            persistent: bool = True,
    ) -> None:
        """Sets the bot's presence for the current connection, if any.

        :param presence: The payload to be sent over the gateway.
        :param persistent:
            If true, this also sets the :attr:`presence` attribute used
            when reconnecting.

        """
        if self._stream is not None:
            payload: Event = {"op": 3, "d": presence}
            try:
                await self._stream.send(payload)
            except websockets.exceptions.ConnectionClosed as e:
                log.error("Client connection closed set_presence %s %s", e, self.token[:10])
                raise

        if persistent:
            self.presence = presence

    async def close(self) -> None:
        """Gracefully closes the current connection."""
        await self._ws.close(1000, reason="Going offline")

    @property
    def _ws(self) -> WebSocketClientProtocol:
        """The current websocket connection.

        :raises RuntimeError:
            No websocket connection is currently active.

        """
        if self._current_websocket is None:
            raise RuntimeError(
                "No active websocket connection; did you call Client.run()?"
            )

        return self._current_websocket

    async def _get_gateway_url(self) -> str:
        from discord_ws import http

        log.debug("Requesting gateway URL %s", self.token[:10])
        async with http.create_httpx_client(token=self.token) as client:
            client.headers["User-Agent"] = self.user_agent
            resp = await client.get("/gateway")
            resp.raise_for_status()
            return resp.json()["url"]

    def _can_resume(self) -> bool:
        return self._resume_gateway_url is not None and self._session_id is not None

    async def _handle_connection(self, *, session_id: str | None) -> None:
        try:
            async with self._create_stream() as stream, self._heart.stay_alive(stream):
                if session_id is None:
                    await self._identify()
                else:
                    await self._resume(session_id)
                await self._receive_loop(session_id=session_id)
        except* HeartbeatLostError:
            await self._ws.close(1002, reason="Heartbeat ACK lost")
            raise

    async def _receive_loop(self, *, session_id: str | None) -> None:
        try:
            while True:
                await self._receive_event()
        except GatewayReconnect:
            await self._ws.close(1002, reason="Reconnect ACK")
            raise
        except SessionInvalidated as e:
            if not e.resumable:
                self._invalidate_session()
            await self._ws.close(1002, reason="Invalid Session ACK")
            raise

    def _add_gateway_params(self, url: str) -> str:
        """Adds query parameters to the given gateway URL.

        .. seealso:: https://discord.com/developers/docs/topics/gateway#connecting-gateway-url-query-string-params

        """
        import urllib.parse

        params = {
            "encoding": "json",
            "v": constants.API_VERSION,
        }

        if self.compress:
            params["compress"] = "zlib-stream"

        return url + "?" + urllib.parse.urlencode(params)

    @asynccontextmanager
    async def _connect(self, url: str) -> AsyncIterator[WebSocketClientProtocol]:
        """Connects to the gateway URL and sets it as the current websocket."""
        connector = websockets.client.connect(
            self._add_gateway_params(url),
            user_agent_header=self.user_agent,
            extra_headers={
                "Accept-Encoding": "gzip, deflate, br, zstd",
                "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh-TW;q=0.7,zh;q=0.6",
                "Pragma":"no-cache",
                "Cache-Control":"no-cache",
            },
            origin="https://discord.com",
            # compression=None,
        )

        log.debug("Creating websocket connection %s", self.token[:10])

        async with connector as ws:
            self._current_websocket = ws
            try:
                yield ws
            finally:
                self._current_websocket = None

    @asynccontextmanager
    async def _create_stream(self) -> AsyncIterator[Stream]:
        """Creates the stream to be used for communicating with the gateway."""
        if self.compress:
            stream = ZLibStream(self._ws)
        else:
            stream = PlainTextStream(self._ws)

        self._stream = stream
        try:
            async with stream:
                yield stream
        finally:
            self._stream = None

    async def _identify(self) -> None:
        """Identifies the client with Discord.

        Note that the client can only identify 1000 times in 24 hours,
        and cannot exceed the ``max_concurrency`` threshold specified
        by the Get Gateway Bot endpoint.

        .. seealso:: https://discord.com/developers/docs/topics/gateway#identifying

        """
        assert self._stream is not None
        payload = await self._create_identify_payload()
        log.debug("Sending identify payload %s", self.token[:10])
        try:
            await self._stream.send(payload)
        except websockets.exceptions.ConnectionClosed as e:
            log.error("Client connection closed _identify %s %s", e, self.token[:10])
            raise

    async def _create_identify_payload(self) -> Event:
        metadata = get_distribution_metadata()
        browser = parse_user_agent(self.user_agent)
        d = {
            # "token": self.token,
            # "intents": self.intents,
            # "properties": {
            #     "os": sys.platform,
            #     "browser": metadata["Name"],
            #     "device": metadata["Name"],
            # },
            "capabilities": 16381,
            "client_state": {
                "api_code_version": 0,
                "highest_last_message_id": "0",
                "read_state_version": 0,
                "user_guild_settings_version": -1,
                "private_channels_version": "0",
                "user_settings_version": -1,
                "guild_versions": {

                }
            },
            "compress": False,
            "presence": {
                "activities": [

                ],
                "afk": False,
                "since": 0,
                "status": "online"
            },
            "token": self.token,
            "intents": self.intents,
            "properties": {
                "os": sys.platform,
                "browser": metadata["Name"],
                "device": metadata["Name"],
            },
            "properties": {
                "referer": "https://www.midjourney.com",
                "os": browser.get("os"),
                "referring_domain_current": "",
                "client_event_source": None,
                "referrer_current": "",
                "system_locale": "zh-CN",
                "browser": browser.get("browser"),
                "release_channel": "stable",
                "browser_version": browser.get("browser_version"),
                "device": "",
                "browser_user_agent": self.user_agent,
                "client_build_number": 222963,
                "referring_domain": "www.midjourney.com"
            },
            # TODO: payload compression
            # TODO: sharding
        }
        if self.large_threshold is not None:
            d["large_threshold"] = self.large_threshold
        if self.presence is not None:
            d["presence"] = self.presence

        return {"op": 2, "d": d}

    async def _resume(self, session_id: str) -> None:
        """Resumes the given session with Discord.

        .. seealso:: https://discord.com/developers/docs/topics/gateway#resuming

        """
        assert self._stream is not None
        payload = await self._create_resume_payload(session_id)
        log.debug("Sending resume payload %s", self.token[:10])
        try:
            await self._stream.send(payload)
        except websockets.exceptions.ConnectionClosed as e:
            log.error("Client connection closed _resume %s %s", e, self.token[:10])
            raise

    async def _create_resume_payload(self, session_id: str) -> Event:
        return {
            "op": 6,
            "d": {
                "token": self.token,
                "session_id": session_id,
                "seq": self._heart.sequence,
            },
        }

    async def _receive_event(self) -> None:
        """Receives and processes an event from the websocket.

        .. seealso:: https://discord.com/developers/docs/topics/opcodes-and-status-codes#gateway-gateway-opcodes

        """
        assert self._stream is not None
        event = await self._stream.recv()

        log.debug("Received event sequence %s %s", event, self.token[:10])

        if event["op"] == 0:
            # Dispatch
            event = cast(DispatchEvent, event)
            log.debug("Received %s event sequence %s %s", event["t"], str(event["s"]) if event["s"] is not None else "None", self.token[:10])

            self._heart.sequence = event["s"]

            if event["t"] == "READY":
                self._resume_gateway_url = event["d"]["resume_gateway_url"]
                self._session_id = event["d"]["session_id"]

            self._dispatch(event)

        elif event["op"] == 1:
            # Heartbeat
            log.debug("Received request to heartbeat %s", self.token[:10])
            self._heart.beat_soon()

        elif event["op"] == 7:
            # Reconnect
            log.debug("Received request to reconnect %s", self.token[:10])
            raise GatewayReconnect()

        elif event["op"] == 9:
            # Invalid Session
            event = cast(InvalidSession, event)
            log.debug("Session has been invalidated %s", self.token[:10])
            raise SessionInvalidated(resumable=event["d"])

        elif event["op"] == 10:
            # Hello
            event = cast(Hello, event)
            log.debug("Received hello from gateway %s", self.token[:10])
            await self._heart.set_interval(event["d"]["heartbeat_interval"] / 1000)

        elif event["op"] == 11:
            # Heartbeat ACK
            log.debug("Received heartbeat acknowledgement %s", self.token[:10])
            self._heart.acknowledged = True
        else:
            log.warning("Received unknown opcode %d %s", event["op"], self.token[:10])

    def _dispatch(self, event: DispatchEvent) -> None:
        """Dispatches an event using the callback assigned by :meth:`on_dispatch()`."""
        if self._dispatch_func is None:
            return

        ret = self._dispatch_func(event)
        if inspect.iscoroutine(ret) or inspect.isawaitable(ret):
            ret = asyncio.ensure_future(ret)
        if asyncio.isfuture(ret):
            self._dispatch_futures.add(ret)
            ret.add_done_callback(self._dispatch_futures.discard)

    def _invalidate_session(self) -> None:
        self._session_id = None

    def _handle_connection_closed(self, e: ConnectionClosed) -> bool:
        """
        Handles connection closure and either raises an exception or returns
        a boolean indicating if the client is allowed to reconnect.
        """
        if e.rcvd is None and e.sent is None:
            log.info("Connection lost, can reconnect %s", self.token[:10])
            return True
        elif e.sent is not None and not e.rcvd_then_sent:
            # 1000 / 1001 causes our client to appear offline,
            # in which case we probably don't want to reconnect
            reconnect = e.sent.code not in WEBSOCKET_CLOSE_CODES
            if reconnect:
                message = "Closed by us with %d, can reconnect %s"
            else:
                message = "Closed by us with %d, will not reconnect %s"
            log.info(message, e.sent.code, self.token[:10])
            return reconnect
        elif e.rcvd is not None:
            code = e.rcvd.code
            reason = self._get_connection_closed_reason(e.rcvd)

            log.debug("Connection closed with %s %s", code, self.token[:10])

            if code in GATEWAY_CANNOT_RESUME_CLOSE_CODES:
                self._invalidate_session()

            if code in WEBSOCKET_CLOSE_CODES:
                self._invalidate_session()
                action = "Closed with %s, websocket closed %s"
                log.info(action, reason, self.token[:10])
            elif code not in GATEWAY_RECONNECT_CLOSE_CODES:
                exc = self._make_connection_closed_error(code, reason)
                raise exc from None
            elif self._can_resume():
                action = "Closed with %s, session can be resumed %s"
                log.info(action, reason, self.token[:10])
            else:
                action = "Closed with %s, session cannot be resumed %s"
                log.info(action, reason, self.token[:10])
            return True
        # We only have e.sent, but e.rcvd_then_sent is True?
        log.exception("Ignoring unusual ConnectionClosed exception %s", self.token[:10])
        return True

    def _get_connection_closed_reason(self, close: websockets.frames.Close) -> str:
        reason = GATEWAY_CLOSE_CODES.get(close.code)
        if reason is not None:
            return f"{close.code} {reason}"
        return str(close)

    def _make_connection_closed_error(
            self,
            code: int,
            reason: str,
    ) -> ConnectionClosedError:
        """Creates an exception for the given close code."""
        if code == 4004:
            return AuthenticationFailedError(code, reason)
        elif code == 4014:
            return PrivilegedIntentsError(
                self.intents & Intents.privileged(),
                code,
                reason,
            )
        return ConnectionClosedError(code, reason)

    @property
    def session_id(self) -> str | None:
        return self._session_id
