#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一日志配置。

默认输出到 stderr（systemd 会收进 journald，可用 `journalctl -u or-dashboard -f` 查看）。
所有模块通过 `get_logger(__name__)` 获取以 `or_dashboard.` 为前缀的子 logger。
"""
import logging
import sys

_configured = False


def setup_logging(level=logging.INFO):
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    )
    logger = logging.getLogger("or_dashboard")
    logger.setLevel(level)
    logger.addHandler(handler)
    logger.propagate = False
    _configured = True


def get_logger(name="or_dashboard"):
    """取得带统一前缀的 logger；`name` 传 __name__ 即可。"""
    if not name or name == "or_dashboard":
        return logging.getLogger("or_dashboard")
    return logging.getLogger("or_dashboard." + name)


# 导入即配置，保证模块级 logger 在任何入口下都有可用 handler
setup_logging()