import hashlib
import random
import time

import db

_codes = {}


def register(username, password):
    pwd_hash = hashlib.md5(password.encode()).hexdigest()
    return db.execute("insert into users(username, password) values (?, ?)", (username, pwd_hash))


def login(username, password):
    pwd_hash = hashlib.md5(password.encode()).hexdigest()
    rows = db.query("select id, username from users where username = ? and password = ?", (username, pwd_hash))
    return rows[0] if rows else None


def send_sms_code(phone):
    code = str(random.randint(100000, 999999))
    _codes[phone] = (code, time.time())
    # 调短信平台发送（略）
    return True


def login_by_sms(phone, code):
    saved = _codes.get(phone)
    if saved and saved[0] == code and time.time() - saved[1] < 300:
        rows = db.query("select id, username from users where phone = ?", (phone,))
        return rows[0] if rows else None
    return None
