# src/config.py
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict

# --------------------------------------------------------------------------- #
# 1. 兼容 tomllib / tomli                                                    #
# --------------------------------------------------------------------------- #
try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # <3.11
    try:
        import tomli as tomllib  # type: ignore
    except ModuleNotFoundError:  # pragma: no cover
        sys.stderr.write(
            "[config] ERROR: tomllib/tomli missing. "
            "Run `pip install tomli` for Python ≤3.10\n"
        )
        raise

# --------------------------------------------------------------------------- #
# 2. 默认值                                                                   #
# --------------------------------------------------------------------------- #
_DEFAULTS: Dict[str, Any] = {
    "cookie": "",
    "username": "",
    "password": "",
    "captcha_key": "",
    # 网络与节流
    "timeout": 20,
    "min_wait": 1.0,
    "max_wait": 3.0,
}


class Settings:
    """读取 config.toml + 环境变量，提供属性化访问。"""

    def __init__(self, path: Path | str = "config.toml") -> None:
        self._raw: Dict[str, Any] = dict(_DEFAULTS)  # deepcopy
        self._load_from_toml(Path(path))
        self._override_from_env()

        # 简单校验
        if not (self.cookie or (self.username and self.password)):
            raise ValueError(
                "[config] 必须提供 cookie，或 username+password 二选一"
            )

    # --------------------------------------------------------------------- #
    # public attribute helpers                                              #
    # --------------------------------------------------------------------- #
    def __getattr__(self, item: str) -> Any:
        if item in self._raw:
            return self._raw[item]
        raise AttributeError(item)

    # --------------------------------------------------------------------- #
    # utils                                                                 #
    # --------------------------------------------------------------------- #
    def _load_from_toml(self, file_path: Path) -> None:
        if not file_path.exists():
            # 若仓库里没有 config.toml，可忽略
            return
        with file_path.open("rb") as fp:
            data = tomllib.load(fp)
        # 支持 [account] / [run] 这类分节，也允许顶层键
        for section in data.values() if isinstance(data, dict) else []:
            if isinstance(section, dict):
                self._raw.update(section)
        self._raw.update({k: v for k, v in data.items() if k in _DEFAULTS})

    def _override_from_env(self) -> None:
        """使用环境变量覆盖，同名优先。名称不区分大小写。"""
        for key in _DEFAULTS:
            env_val = os.getenv(key.upper()) or os.getenv(key.lower())
            if env_val is None:
                continue
            # 尝试把数字型转换成 int/float
            if key in {"timeout"}:
                env_val = int(env_val)
            if key in {"min_wait", "max_wait"}:
                env_val = float(env_val)
            self._raw[key] = env_val

    # --------------------------------------------------------------------- #
    # helper exports                                                        #
    # --------------------------------------------------------------------- #
    def as_dict(self) -> Dict[str, Any]:
        """返回去除敏感信息（password/cookie）的安全字典，可用于日志。"""
        safe = {
            k: ("***" if k in {"password", "cookie"} else v)
            for k, v in self._raw.items()
        }
        return safe

    # nice repr
    def __repr__(self) -> str:
        safe = self.as_dict()
        return f"Settings({safe})"