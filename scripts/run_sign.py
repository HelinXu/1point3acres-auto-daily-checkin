from src.config import Settings
from src.client import P3ASession
from src.signer import sign_today

cfg   = Settings()                        # captcha_key 放 config.toml 或 Secret
sess  = P3ASession(cfg)
sess.login()
print(sign_today(sess,
                 mood="yl",
                 text="每日打卡 https://github.com/HelinXu/autosign_1point3acres",
                 captcha_api_key=cfg.captcha_key))