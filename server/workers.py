"""背景工作執行緒：Webhook 重試、排程推播、舊紀錄清理。"""
import logging
import threading
import time

import localconfig as cfg
import scheduled_push
import webhook_delivery

logger = logging.getLogger("LocalBotPlatform")

PURGE_INTERVAL = 6 * 3600
_lock = threading.Lock()
_threads = []
_stop = threading.Event()


def _loop(name: str, interval: float, fn):
    while not _stop.is_set():
        try:
            fn()
        except Exception:  # noqa: BLE001 - 一次失敗不能讓工作執行緒死掉
            logger.exception(f"背景工作 {name} 發生錯誤")
        _stop.wait(interval)


def purge(ctx):
    cutoff = int((time.time() - cfg.LOG_RETENTION_DAYS * 86400) * 1000)
    result = ctx.db.purge_logs(cutoff)
    if result["deliveries"] or result["runs"]:
        logger.info(f"已清除 {cfg.LOG_RETENTION_DAYS} 天前的紀錄：轉送 {result['deliveries']} 筆、排程執行 {result['runs']} 筆")


def start(ctx):
    """啟動背景執行緒（只會啟動一次）。"""
    with _lock:
        if _threads:
            return _threads
        _stop.clear()
        try:
            n = ctx.db.recover_sending()
            if n:
                logger.info(f"上次中斷的 {n} 筆 webhook 轉送已排回重試")
            purge(ctx)
        except Exception:  # noqa: BLE001
            logger.exception("背景工作初始化失敗")
        last_purge = [time.time()]

        def housekeeping():
            if time.time() - last_purge[0] >= PURGE_INTERVAL:
                last_purge[0] = time.time()
                purge(ctx)

        jobs = (("webhook-retry", 1.0, webhook_delivery.process_due),
                ("scheduler", 5.0, scheduled_push.process_due),
                ("housekeeping", 600.0, housekeeping))
        for name, interval, fn in jobs:
            t = threading.Thread(target=_loop, args=(name, interval, fn), name=f"localbot-{name}", daemon=True)
            t.start()
            _threads.append(t)
        logger.info("背景工作已啟動：webhook 重試、排程推播")
        return _threads


def stop():
    """測試用。"""
    _stop.set()
    with _lock:
        for t in _threads:
            t.join(timeout=2)
        _threads.clear()
