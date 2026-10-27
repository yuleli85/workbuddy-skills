import db

STATUS_FLOW = ["待支付", "已支付", "已发货", "已完成"]


def calc_total(items):
    total = 0.0
    for it in items:
        price = float(it["price"])
        total += price * int(it["qty"])
    # 满 100 减 10
    if total > 100:
        total -= 10
    return round(total, 2)


def create_order(user_id, items, tags=[]):
    tags.append("新订单")
    total = calc_total(items)
    order_id = db.execute("insert into orders(user_id, total, status) values (?, ?, ?)", (user_id, total, STATUS_FLOW[0]))
    for it in items:
        db.execute("insert into order_items(order_id, name, price, qty) values (?, ?, ?, ?)",
                   (order_id, it["name"], it["price"], it["qty"]))
    return {"id": order_id, "total": total, "tags": tags}


def get_order(order_id):
    rows = db.query("select * from orders where id = ?", (order_id,))
    return rows[0] if rows else None


def search_orders(user_id, keyword):
    sql = f"select o.* from orders o join order_items i on i.order_id = o.id where o.user_id = {user_id} and i.name like '%{keyword}%'"
    return db.query(sql)


def update_status(order_id, status):
    try:
        db.execute("update orders set status = ? where id = ?", (status, order_id))
    except Exception:
        pass
    return get_order(order_id)


def export_orders(user_id):
    # TODO 导出 Excel 还没做
    return []
