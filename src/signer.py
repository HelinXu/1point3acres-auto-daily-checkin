# src/signer.py
from __future__ import annotations
import time
import json
import re
import requests
from typing import Optional
from loguru import logger
from .client import P3ASession

# 固定 Turnstile sitekey，避免页面请求被 WAF 拦截
SITEKEY = "0x4AAAAAAAA6iSaNNPWafmlz"
# 签到 API
API_URL = "https://api.1point3acres.com/api/users/checkin"
# 签到页面 URL（仅用于 pageurl 参数传给 2captcha）
CHECKIN_PAGE = "https://www.1point3acres.com/next/daily-checkin"

# ────────────────────────── Turnstile Solver ─────────────────────────
def solve_turnstile(sitekey: str, api_key: str, page_url: str, timeout: int = 120) -> str:
    """使用 2captcha 获取 Cloudflare Turnstile token"""
    in_url = (
        "http://2captcha.com/in.php"
        f"?key={api_key}&method=turnstile"
        f"&sitekey={sitekey}&pageurl={page_url}"
    )
    task_id = requests.get(in_url, timeout=20).text.split("|")[-1]
    logger.debug(f"2captcha task id={task_id}")
    time.sleep(20)
    for _ in range(timeout // 5):
        res = requests.get(
            f"http://2captcha.com/res.php?key={api_key}&action=get&id={task_id}",
            timeout=20
        ).text
        if res == "CAPCHA_NOT_READY":
            time.sleep(5)
            continue
        if "|" in res:
            token = res.split("|", 1)[1]
            logger.debug(f"2captcha solved token length={len(token)}")
            return token
        raise RuntimeError(f"2captcha error: {res}")
    raise TimeoutError("Turnstile solve timeout")

# ────────────────────────── 主入口 ─────────────────────────────────
def sign_today(
    sess: P3ASession,
    mood: str = "kx",
    text: str = "签到，今日加油！",
    captcha_api_key: Optional[str] = None
) -> str:
    """
    自动签到并返回提示。

    Parameters
    ----------
    sess: P3ASession         已登录的会话
    mood: str               心情代码，14 种之一
    text: str               今日想说的话
    captcha_api_key: str    2captcha API key
    """
    # 1) 直接使用固定的 sitekey，跳过 GET 页面
    sitekey = SITEKEY
    logger.debug(f"Use fixed Turnstile sitekey={sitekey}")

    # 2) 获取 Turnstile token
    if not captcha_api_key:
        raise RuntimeError("缺少 captcha_api_key，无法获取 Turnstile token")
    token = solve_turnstile(sitekey, captcha_api_key, CHECKIN_PAGE)
    logger.debug("2captcha token ok")

    # 3) 提交签到请求
    payload = {
        "qdxq": mood,
        "todaysay": text,
        "captcha_response": token,
        "version": 2,
    }
    resp_text = sess.post(
        API_URL,
        data=json.dumps(payload),
        headers={
            "Content-Type": "application/json",
            "Origin": "https://www.1point3acres.com"
        }
    )

    # 4) 解析响应
    try:
        data = json.loads(resp_text)
    except Exception:
        logger.error(f"非 JSON 响应:\n{resp_text[:200]}")
        raise

    msg = data.get("msg", "")
    errno = data.get("errno")
    # 成功
    if msg.startswith(("签到成功", "恭喜你签到成功")):
        logger.success(f"✅ {msg}")
        return msg
    # 已经签到的场景：返回 errno -1 或 msg 包含 '已经签到' 字样
    if errno == -1 or "已经签到" in msg:
        logger.info(f"今日已签到：{msg}")
        return "已签到 ✓"
    # 其他错误
    raise RuntimeError(f"签到失败：{data}")
