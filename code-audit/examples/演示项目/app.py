import yaml
from flask import Flask, jsonify, request, session

import config
from services import order, user

app = Flask(__name__)
app.config.from_object(config)


def current_user():
    return session.get("uid")


@app.post("/api/register")
def register():
    data = request.get_json()
    uid = user.register(data["username"], data["password"])
    return jsonify({"code": 0, "id": uid})


@app.post("/api/login")
def login():
    data = request.get_json()
    u = user.login(data["username"], data["password"])
    if not u:
        return jsonify({"code": 1, "msg": "用户名或口令错误"})
    session["uid"] = u["id"]
    return jsonify({"code": 0, "user": u})


@app.post("/api/sms/send")
def sms_send():
    user.send_sms_code(request.get_json()["phone"])
    return jsonify({"code": 0})


@app.post("/api/sms/login")
def sms_login():
    data = request.get_json()
    u = user.login_by_sms(data["phone"], data["code"])
    if not u:
        return jsonify({"code": 1, "msg": "验证码错误"})
    session["uid"] = u["id"]
    return jsonify({"code": 0, "user": u})


@app.post("/api/orders")
def create_order():
    if not current_user():
        return jsonify({"code": 401}), 401
    return jsonify({"code": 0, "data": order.create_order(current_user(), request.get_json()["items"])})


@app.get("/api/orders/<int:order_id>")
def get_order(order_id):
    if not current_user():
        return jsonify({"code": 401}), 401
    return jsonify({"code": 0, "data": order.get_order(order_id)})


@app.get("/api/orders/search")
def search():
    if not current_user():
        return jsonify({"code": 401}), 401
    return jsonify({"code": 0, "data": order.search_orders(current_user(), request.args.get("q", ""))})


@app.post("/api/orders/<int:order_id>/status")
def change_status(order_id):
    if not current_user():
        return jsonify({"code": 401}), 401
    return jsonify({"code": 0, "data": order.update_status(order_id, request.get_json()["status"])})


@app.post("/api/orders/import")
def import_orders():
    data = yaml.load(request.data)
    for o in data.get("orders", []):
        order.create_order(current_user(), o["items"])
    return jsonify({"code": 0})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
