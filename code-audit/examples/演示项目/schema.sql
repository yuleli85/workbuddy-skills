create table if not exists users (id integer primary key autoincrement, username text unique, password text, phone text);
create table if not exists orders (id integer primary key autoincrement, user_id integer, total real, status text);
create table if not exists order_items (id integer primary key autoincrement, order_id integer, name text, price real, qty integer);
