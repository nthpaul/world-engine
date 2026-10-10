"""Bounded fixed-destination byte relay; never accepts a proxy destination."""

import asyncio
import os

UPSTREAM = os.environ["GITLAB_UPSTREAM"]
MAX_CONNECTIONS = 32
active = 0


async def relay(reader, writer):
    global active
    if active >= MAX_CONNECTIONS:
        writer.close()
        return
    active += 1
    remote = None
    try:
        upstream, remote = await asyncio.wait_for(asyncio.open_connection(UPSTREAM, 80), 5)

        async def pipe(source, target):
            while data := await asyncio.wait_for(source.read(65_536), 60):
                target.write(data)
                await target.drain()

        tasks = [asyncio.create_task(pipe(reader, remote)), asyncio.create_task(pipe(upstream, writer))]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    except (OSError, TimeoutError):
        pass
    finally:
        if remote is not None:
            remote.close()
        writer.close()
        active -= 1


async def main():
    server = await asyncio.start_server(relay, "0.0.0.0", 8080, backlog=32)
    async with server:
        await server.serve_forever()


asyncio.run(main())
