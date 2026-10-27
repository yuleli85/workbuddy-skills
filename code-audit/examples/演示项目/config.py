import os

DEBUG = True
SECRET_KEY = "f3a9c1e7b2d84f60"
DATABASE = os.environ.get("ORDER_DB", "orders.db")
SMS_API_KEY = os.getenv("SMS_API_KEY")
