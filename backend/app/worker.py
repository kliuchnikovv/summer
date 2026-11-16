"""Worker entrypoint: `python -m app.worker`."""
import asyncio

from app.interfaces.worker import run_worker

if __name__ == "__main__":
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        pass
