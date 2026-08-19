import logging

def configure_logger(product_id: str, level: int = logging.INFO) -> logging.Logger:
    """
    Configures structured logging for the SDK.
    """
    logger = logging.getLogger(f"rexycore.client.{product_id}")
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    
    logger.setLevel(level)
    return logger
