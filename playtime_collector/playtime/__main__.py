import logging

import uvicorn

from . import config


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Quieten noisy per-poll/per-request logs so our own activity lines stand out.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("psnawp_api").setLevel(logging.WARNING)
    uvicorn.run(
        "playtime.api:app",
        host="0.0.0.0",
        port=config.HTTP_PORT,
        log_level="warning",
        access_log=False,
    )


if __name__ == "__main__":
    main()
