import asyncio
import os
import uvicorn
import chat_manager
from admin_server import app


async def main():
    await chat_manager.load()
    config = uvicorn.Config(app, host="0.0.0.0", port=8080, log_level="warning",
                            proxy_headers=True, forwarded_allow_ips="*",
                            root_path=os.environ.get("ROOT_PATH", ""))
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
