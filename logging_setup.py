import logging
import os
import platform
import sys
from logging.handlers import RotatingFileHandler


def setup_logging(logs_dir: str, app_name: str = "NRC1", level: int = logging.INFO) -> logging.Logger:
    os.makedirs(logs_dir, exist_ok=True)
    logger = logging.getLogger(app_name)
    logger.setLevel(level)

    if not any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
        log_path = os.path.join(logs_dir, "app.log")
        handler = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=10, encoding="utf-8")
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s")
        handler.setFormatter(fmt)
        logger.addHandler(handler)

    if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
        sh = logging.StreamHandler(stream=sys.stdout)
        sh.setLevel(level)
        sh.setFormatter(logging.Formatter("%(levelname)s - %(message)s"))
        logger.addHandler(sh)

    logger.info("Logging initialized")
    logger.info("Python=%s Platform=%s", sys.version.replace("\n", " "), platform.platform())
    return logger

