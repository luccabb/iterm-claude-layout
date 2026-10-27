from __future__ import annotations

import asyncio
import logging
from logging.handlers import RotatingFileHandler

import iterm2

from . import snapshot, store

PERIOD = 15
SETTLE = 3
log = logging.getLogger("iterm-claude-layout")


async def main(connection: iterm2.Connection) -> None:
    held = store.lock()
    if held is None:
        print("another snapshot loop is already running")
        return
    handler = RotatingFileHandler(store.ROOT / "daemon.log", maxBytes=1 << 20, backupCount=1)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)

    app = await iterm2.async_get_app(connection)
    changed = asyncio.Event()

    async def watch_layout():
        async with iterm2.LayoutChangeMonitor(connection) as monitor:
            while True:
                await monitor.async_get()
                changed.set()

    watcher = asyncio.ensure_future(watch_layout())
    last = store.latest_fingerprint()
    log.info("started")
    while not watcher.done():
        try:
            fp = store.save(await snapshot.capture(app), last)
            if fp != last:
                log.info("saved %s", fp)
            last = fp
        except Exception:
            log.exception("snapshot failed")
        try:
            await asyncio.wait_for(changed.wait(), PERIOD)
        except asyncio.TimeoutError:
            continue
        # Save only once the layout holds still, so an iTerm quit tearing windows down is never recorded.
        while True:
            changed.clear()
            try:
                await asyncio.wait_for(changed.wait(), SETTLE)
            except asyncio.TimeoutError:
                break
    watcher.result()
