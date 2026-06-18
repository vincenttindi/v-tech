"""
VIN TECH - Flask E-commerce System
==================================
Features:
- SQLite Database
- User Authentication
- Shopping Cart (Session)
- M-Pesa STK Push (Till: 4381910)
- Orders Storage
- Admin Dashboard
"""

from flask import (
    Flask, render_template, request,
    redirect, url_for, flash,
    session, jsonify
)

import sqlite3
import requests
import base64
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import os

# ==========================================================
# APP CONFIG
# ==========================================================
app = Flask(__name__)
app.secret_key = "vintech_super_secret_key"

DATABASE = "vintech.db"

# ==========================================================
# M-PESA CONFIG
# ==========================================================
CONSUMER_KEY = "YOUR_CONSUMER_KEY"
CONSUMER_SECRET = "YOUR_CONSUMER_SECRET"
BUSINESS_SHORT_CODE = "4381910"
PASSKEY = "YOUR_PASSKEY"
CALLBACK_URL = "https://yourdomain.com/mpesa_callback"

# ==========================================================
# DATABASE CONNECTION
# ==========================================================
def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

# ==========================================================
# CREATE TABLES
# ==========================================================
def create_tables():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            phone TEXT,
            amount REAL,
            status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT,
            message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()

create_tables()

# ==========================================================
# M-PESA FUNCTIONS
# ==========================================================
def get_access_token():
    url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    response = requests.get(url, auth=(CONSUMER_KEY, CONSUMER_SECRET))
    return response.json()["access_token"]

def generate_password():
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    data = BUSINESS_SHORT_CODE + PASSKEY + timestamp
    password = base64.b64encode(data.encode()).decode()
    return password, timestamp

# ==========================================================
# ROUTES
# ==========================================================
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/products")
def products():
    return render_template("products.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"]
        password = generate_password_hash(request.form["password"])

        conn = get_db_connection()
        try:
            conn.execute("""
                INSERT INTO users (username, email, password)
                VALUES (?, ?, ?)
            """, (username, email, password))

            conn.commit()
            flash("Account created successfully!")
            return redirect(url_for("login"))

        except sqlite3.IntegrityError:
            flash("Email already exists!")

        finally:
            conn.close()

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        conn = get_db_connection()
        user = conn.execute(
            "SELECT * FROM users WHERE email=?",
            (email,)
        ).fetchone()
        conn.close()

        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["is_admin"] = user["is_admin"]

            flash("Login successful!")
            return redirect(url_for("client"))

        flash("Invalid login credentials")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully")
    return redirect(url_for("home"))

@app.route("/client")
def client():
    if "user_id" not in session:
        return redirect(url_for("login"))

    return render_template("client.html")

@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        message = request.form["message"]

        conn = get_db_connection()
        conn.execute("""
            INSERT INTO contacts (name, email, message)
            VALUES (?, ?, ?)
        """, (name, email, message))
        conn.commit()
        conn.close()

        flash("Message sent successfully!")
        return redirect(url_for("contact"))

    return render_template("contact.html")

# ==========================================================
# CART SYSTEM
# ==========================================================
@app.route("/add_to_cart", methods=["POST"])
def add_to_cart():
    product = request.form["product"]
    price = float(request.form["price"])

    if "cart" not in session:
        session["cart"] = []

    session["cart"].append({
        "product": product,
        "price": price
    })

    session.modified = True
    flash(f"{product} added to cart")
    return redirect(url_for("products"))

@app.route("/cart")
def cart():
    cart_items = session.get("cart", [])
    total = sum(item["price"] for item in cart_items)
    return render_template("cart.html", cart=cart_items, total=total)

@app.route("/remove_from_cart/<int:index>")
def remove_from_cart(index):
    if "cart" in session:
        cart = session["cart"]

        if 0 <= index < len(cart):
            removed = cart.pop(index)
            session["cart"] = cart
            session.modified = True
            flash(f"{removed['product']} removed from cart")

    return redirect(url_for("cart"))

@app.route("/clear_cart")
def clear_cart():
    session.pop("cart", None)
    flash("Cart cleared")
    return redirect(url_for("cart"))

# ==========================================================
# M-PESA CHECKOUT
# ==========================================================
@app.route("/checkout", methods=["POST"])
def checkout():
    phone = request.form["phone"]
    cart_items = session.get("cart", [])

    if not cart_items:
        flash("Cart is empty")
        return redirect(url_for("cart"))

    amount = int(sum(item["price"] for item in cart_items))

    access_token = get_access_token()
    password, timestamp = generate_password()

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    payload = {
        "BusinessShortCode": BUSINESS_SHORT_CODE,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerBuyGoodsOnline",
        "Amount": amount,
        "PartyA": phone,
        "PartyB": BUSINESS_SHORT_CODE,
        "PhoneNumber": phone,
        "CallBackURL": CALLBACK_URL,
        "AccountReference": "Vin Tech",
        "TransactionDesc": "Purchase"
    }

    response = requests.post(
        "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest",
        json=payload,
        headers=headers
    )

    result = response.json()

    if result.get("ResponseCode") == "0":
        flash("STK Push sent to your phone")

        conn = get_db_connection()
        conn.execute("""
            INSERT INTO orders (username, phone, amount, status)
            VALUES (?, ?, ?, ?)
        """, (
            session.get("username"),
            phone,
            amount,
            "Pending"
        ))
        conn.commit()
        conn.close()

    else:
        flash("Payment failed")

    return redirect(url_for("cart"))

# ==========================================================
# ADMIN
# ==========================================================
@app.route("/admin")
def admin():
    conn = get_db_connection()
    orders = conn.execute("SELECT * FROM orders ORDER BY created_at DESC").fetchall()
    conn.close()

    return render_template("admin.html", orders=orders)

# ==========================================================
# RUN APP (PRODUCTION READY)
# ==========================================================
if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=True
    )