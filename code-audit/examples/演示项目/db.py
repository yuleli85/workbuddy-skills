import sqlite3

import config


def get_conn():
    conn = sqlite3.connect(config.DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def query(sql, params=()):
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def execute(sql, params=()):
    with get_conn() as conn:
        cur = conn.execute(sql, params)
        return cur.lastrowid
