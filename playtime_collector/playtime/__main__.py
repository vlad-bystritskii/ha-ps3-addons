import logging

import uvicorn

from . import config


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run("playtime.api:app", host="0.0.0.0", port=config.HTTP_PORT, log_level="info")


if __name__ == "__main__":
    main()
