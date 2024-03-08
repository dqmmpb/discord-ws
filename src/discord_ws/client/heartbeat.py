from __future__ import annotations

import asyncio
import logging
import random
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator, Self, cast

from discord_ws.errors import HeartbeatLostError

if TYPE_CHECKING:
    from . import Event, Stream

log = logging.getLogger(__name__)


class Heart:
    """Manages the heartbeat loop for a client's connections."""

    acknowledged: bool
    """
    Indicates if the last heartbeat was acknowledged.

    This is set to False every time a heartbeat is sent.
    If the heart does not receive an acknowledgement before the next
    heartbeat, the heartbeat loop will stop and the connection will
    be terminated.

    This attribute should be updated by the caller.
    """

    sequence: int | None
    """
    The last sequence number received from Discord.

    This attribute should be updated by the caller.
    """

    token: str
    """The token to use for authenticating with the gateway."""

    def __init__(self, token: str) -> None:
        self.token = token
        self.acknowledged = True
        self.sequence = None

        self._interval = None
        self._interval_cond = asyncio.Condition()
        self._beat_event = asyncio.Event()
        self._rand = random.Random()

    @asynccontextmanager
    async def stay_alive(self, stream: Stream) -> AsyncIterator[Self]:
        """A context manager that keeps the heart alive.

        The client must have a connection established before this
        context manager can be used.

        After exiting, the interval is cleared and must be reset again.

        If the heartbeat is not acknowledged, the connection will be closed
        and the current task cancelled.

        :param stream: The stream to send heartbeats to.
        :raises asyncio.TimeoutError:
            The heart's interval was not set in time.
        :raises HeartbeatLostError:
            The last heartbeat was not acknowledged in time.

        """
        try:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(self._run(stream))
                yield self
        finally:
            await self.set_interval(None)
            self.acknowledged = True
            # self.sequence should not be reset because it needs to persist
            # between connections when resuming

    def beat_soon(self) -> None:
        """Skips the current interval to trigger the next heartbeat."""
        self._beat_event.set()

    @property
    def interval(self) -> float | None:
        """The heartbeat interval given by Discord.

        This must be set using :meth:`set_interval()` before
        the heartbeat loop can be started.

        """
        return self._interval

    async def set_interval(self, interval: float | None) -> None:
        """Sets the heartbeat interval, notifying the heart of any changes."""
        self._interval = interval
        if self._interval is not None:
            log.debug("Received interval %.2fs for heartbeat %s", self._interval, self.token[:10])
        else:
            log.debug("Received interval None for heartbeat %s", self.token[:10])
        async with self._interval_cond:
            self._interval_cond.notify_all()

    async def _run(self, stream: Stream) -> None:
        """Runs the heartbeat loop indefinitely."""
        while True:
            await self._sleep()
            await self._send_heartbeat(stream)

    async def _sleep(self) -> None:
        """Sleeps until the next heartbeat interval.

        .. seealso:: https://discord.com/developers/docs/topics/gateway#sending-heartbeats

        """
        await asyncio.wait_for(self._wait_for_interval(), timeout=60.0)
        assert self.interval is not None

        jitter = self._rand.random()
        timeout = self.interval + jitter
        # jitter = self._rand.random()
        # timeout = self.interval * jitter

        try:
            log.debug("Waiting %.2fs for heartbeat %s", timeout, self.token[:10])
            await asyncio.wait_for(self._beat_event.wait(), timeout)
        except asyncio.TimeoutError:
            log.debug("Waiting %.2fs for heartbeat %s timeout", timeout, self.token[:10])
            pass

    async def _wait_for_interval(self) -> float:
        """Waits for the heartbeat interval to be set to a numeric value."""
        async with self._interval_cond:
            await self._interval_cond.wait_for(lambda: self.interval is not None)
            return cast(float, self.interval)

    async def _send_heartbeat(self, stream: Stream) -> None:
        """Sends a heartbeat payload to Discord."""
        if not self.acknowledged:
            log.debug("Heartbeat not acknowledged %s", self.token[:10])
            raise HeartbeatLostError()

        payload = self._create_heartbeat_payload()
        log.debug("Sending heartbeat, last sequence: %s %s", self.sequence, self.token[:10])
        await stream.send(payload)
        log.debug("Sending heartbeat, last sequence: %s %s done", self.sequence, self.token[:10])

        self._beat_event.clear()
        self.acknowledged = False

    def _create_heartbeat_payload(self) -> Event:
        return {"op": 1, "d": self.sequence}
