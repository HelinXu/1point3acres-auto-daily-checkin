# src/client.py
"""
包装与 1point3acres 站点交互的网络层。

核心职责
--------
1. 处理 Cloudflare JS Challenge（cloudscraper 自动完成）
2. 登录（Cookie 优先；否则用用户名+密码）
3. 全局限速（min_wait / max_wait）与自动重试
4. 提供统一的 get / post / soup 便捷方法
"""

from __future__ import annotations

import random
import re
import time
from typing import Any, Dict, Optional

import cloudscraper
from bs4 import BeautifulSoup
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import Settings

BASE = "https://www.1point3acres.com/bbs/"


class P3ASession:
    """封装云端会话，供 signer / crawler 等模块复用。"""

    # ------------------------------------------------------------ #
    # 初始化 & 登录
    # ------------------------------------------------------------ #
    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg
        self.http = cloudscraper.create_scraper(
            browser={"custom": "Mozilla/5.0"}
        )
        # 若直接给了 cookie，就带上；否则稍后会 login()
        if cfg.cookie:
            self.http.headers.update({"cookie": cfg.cookie})

    def login(self) -> None:
        """
        确保会话已登录。
        - 如果 config.toml 中提供了 cookie，就认为已登录，直接跳过所有网络检查。
        - 否则照旧走表单登录流程。
        """
        # 只要你跑 CI 时在 config.toml 里设置了 cookie，就不用再碰 /bbs/ 主页了
        if self.cfg.cookie:
            logger.debug("检测到 cookie，跳过登录检测")
            return

        # 如果没 cookie，就做原来的 Discuz! 表单登录
        if self._is_logged_in():
            logger.debug("已通过 Cookie 登录")
            return

        if not (self.cfg.username and self.cfg.password):
            raise RuntimeError("登录失败：未提供用户名/密码")

        logger.info("尝试表单登录 …")
        self._login_via_form()
        if not self._is_logged_in():
            raise RuntimeError("表单登录失败（可能需要验证码或密码错）")
        logger.success("表单登录成功")

    # ------------------------------------------------------------ #
    # 对外请求接口
    # ------------------------------------------------------------ #
    def get(self, url: str, **kw) -> str:
        """GET 请求并返回文本，自动限速 + 重试"""
        self._sleep_between_requests()
        return self._safe_request("get", url, **kw)

    def post(self, url: str, data: Dict[str, Any], **kw) -> str:
        """POST 请求并返回文本，自动限速 + 重试"""
        self._sleep_between_requests()
        kw.setdefault("data", data)
        return self._safe_request("post", url, **kw)

    def soup(self, url: str, **kw) -> BeautifulSoup:
        """GET→解析→返回 BeautifulSoup 对象"""
        html = self.get(url, **kw)
        return BeautifulSoup(html, "lxml")

    # ------------------------------------------------------------ #
    # 内部方法
    # ------------------------------------------------------------ #
    def _sleep_between_requests(self) -> None:
        delay = random.uniform(self.cfg.min_wait, self.cfg.max_wait)
        time.sleep(delay)

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def _safe_request(self, method: str, url: str, **kw) -> str:
        resp = getattr(self.http, method)(url, timeout=self.cfg.timeout, **kw)
        if resp.status_code in (403, 429):
            logger.warning(
                f"请求被拒绝 {resp.status_code}，重试中 …  URL={url}"
            )
            raise RuntimeError("WAF block, retry")
        return resp.text

    # ---------- 登录辅助 ---------- #
    def _login_via_form(self) -> None:
        # 1) 访问登录页拿 formhash
        login_page = self._safe_request(
            "get", BASE + "member.php?mod=logging&action=login"
        )
        m = re.search(r'name="formhash" value="(\w+)"', login_page)
        if not m:
            raise RuntimeError("无法解析 formhash，页面结构可能已变")
        formhash = m.group(1)

        # 2) 发送登录表单
        payload = {
            "formhash": formhash,
            "username": self.cfg.username,
            "password": self.cfg.password,
            "loginsubmit": "yes",
            "cookietime": "2592000",  # 30 天
        }
        logger.debug("POST 登录表单 …")
        self._safe_request(
            "post",
            BASE + "member.php?mod=logging&action=login&loginsubmit=yes",
            data=payload,
            allow_redirects=False,
        )

    def _is_logged_in(self, html: Optional[str] = None) -> bool:
        """检测用户名是否出现在首页 HTML"""
        if not html:
            html = self._safe_request("get", BASE)
        return self.cfg.username and self.cfg.username in html