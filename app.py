from flask import Flask, jsonify, request
import jwt
import datetime
from functools import wraps
import stripe
import os

app = Flask(__name__)

SECRET_KEY = "mysecretkey"

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

products = [
    {
        "id": 1,
        "name": "Laptop",
        "price": 700,
        "stock": 5
    },
    {
        "id": 2,
        "name": "Headphones",
        "price": 50,
        "stock": 10
    },
    {
        "id": 3,
        "name": "Mouse",
        "price": 25,
        "stock": 20
    }
]

users = []
carts = {}


def token_required(function):
    @wraps(function)
    def decorated(*args, **kwargs):

        auth_header = request.headers.get("Authorization")

        if not auth_header:
            return jsonify({
                "error": "Token is missing"
            }), 401

        try:
            token = auth_header.split(" ")[1]

            data = jwt.decode(
                token,
                SECRET_KEY,
                algorithms=["HS256"]
            )

            current_user_id = data["user_id"]
            current_user_role = data["role"]

        except Exception:
            return jsonify({
                "error": "Invalid or expired token"
            }), 401

        return function(
            current_user_id,
            current_user_role,
            *args,
            **kwargs
        )

    return decorated


@app.route("/")
def home():
    return jsonify({
        "message": "E-Commerce API is running"
    })


@app.route("/products", methods=["GET"])
def get_products():

    search = request.args.get("search")

    if search:
        result = []

        for product in products:
            if search.lower() in product["name"].lower():
                result.append(product)

        return jsonify(result)

    return jsonify(products)


@app.route("/products/<int:product_id>", methods=["GET"])
def get_product(product_id):

    for product in products:
        if product["id"] == product_id:
            return jsonify(product)

    return jsonify({
        "error": "Product not found"
    }), 404


@app.route("/signup", methods=["POST"])
def signup():

    data = request.get_json()

    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({
            "error": "Username and password are required"
        }), 400

    for user in users:
        if user["username"] == username:
            return jsonify({
                "error": "User already exists"
            }), 400

    if len(users) == 0:
        role = "admin"
    else:
        role = "user"

    new_user = {
        "id": len(users) + 1,
        "username": username,
        "password": password,
        "role": role
    }

    users.append(new_user)

    return jsonify({
        "message": "User registered successfully",
        "role": role
    }), 201


@app.route("/login", methods=["POST"])
def login():

    data = request.get_json()

    username = data.get("username")
    password = data.get("password")

    for user in users:

        if user["username"] == username and user["password"] == password:

            token = jwt.encode(
                {
                    "user_id": user["id"],
                    "username": user["username"],
                    "role": user["role"],
                    "exp": datetime.datetime.utcnow()
                    + datetime.timedelta(hours=1)
                },
                SECRET_KEY,
                algorithm="HS256"
            )

            return jsonify({
                "message": "Login successful",
                "role": user["role"],
                "token": token
            })

    return jsonify({
        "error": "Invalid username or password"
    }), 401


@app.route("/cart", methods=["GET"])
@token_required
def view_cart(current_user_id, current_user_role):

    user_cart = carts.get(current_user_id, [])

    total = 0

    for item in user_cart:
        total += item["total"]

    return jsonify({
        "items": user_cart,
        "cart_total": total
    })


@app.route("/cart", methods=["POST"])
@token_required
def add_to_cart(current_user_id, current_user_role):

    data = request.get_json()

    product_id = data.get("product_id")
    quantity = data.get("quantity", 1)

    product = None

    for item in products:
        if item["id"] == product_id:
            product = item
            break

    if not product:
        return jsonify({
            "error": "Product not found"
        }), 404

    if quantity <= 0:
        return jsonify({
            "error": "Quantity must be greater than 0"
        }), 400

    if quantity > product["stock"]:
        return jsonify({
            "error": "Not enough stock"
        }), 400

    if current_user_id not in carts:
        carts[current_user_id] = []

    for cart_item in carts[current_user_id]:

        if cart_item["product_id"] == product_id:

            new_quantity = cart_item["quantity"] + quantity

            if new_quantity > product["stock"]:
                return jsonify({
                    "error": "Not enough stock"
                }), 400

            cart_item["quantity"] = new_quantity
            cart_item["total"] = (
                cart_item["price"] * new_quantity
            )

            return jsonify({
                "message": "Cart updated",
                "item": cart_item
            })

    cart_item = {
        "product_id": product["id"],
        "name": product["name"],
        "price": product["price"],
        "quantity": quantity,
        "total": product["price"] * quantity
    }

    carts[current_user_id].append(cart_item)

    return jsonify({
        "message": "Product added to cart",
        "item": cart_item
    }), 201


@app.route("/cart/<int:product_id>", methods=["DELETE"])
@token_required
def remove_from_cart(
    current_user_id,
    current_user_role,
    product_id
):

    user_cart = carts.get(current_user_id, [])

    for item in user_cart:

        if item["product_id"] == product_id:

            user_cart.remove(item)

            return jsonify({
                "message": "Product removed from cart"
            })

    return jsonify({
        "error": "Product not found in cart"
    }), 404


@app.route("/checkout", methods=["POST"])
@token_required
def checkout(current_user_id, current_user_role):

    user_cart = carts.get(current_user_id, [])

    if not user_cart:
        return jsonify({
            "error": "Cart is empty"
        }), 400

    total_amount = 0

    for cart_item in user_cart:

        product = None

        for item in products:
            if item["id"] == cart_item["product_id"]:
                product = item
                break

        if not product:
            return jsonify({
                "error": "Product no longer exists"
            }), 404

        if cart_item["quantity"] > product["stock"]:
            return jsonify({
                "error": f"Not enough stock for {product['name']}"
            }), 400

        total_amount += cart_item["total"]

    if not stripe.api_key:
        return jsonify({
            "error": "Stripe test key is not configured"
        }), 500

    try:

        payment = stripe.PaymentIntent.create(
            amount=int(total_amount * 100),
            currency="usd",
            payment_method="pm_card_visa",
            confirm=True,
            automatic_payment_methods={
                "enabled": True,
                "allow_redirects": "never"
            }
        )

    except Exception as error:
        return jsonify({
            "error": "Payment failed",
            "details": str(error)
        }), 400

    for cart_item in user_cart:

        for product in products:

            if product["id"] == cart_item["product_id"]:
                product["stock"] -= cart_item["quantity"]
                break

    purchased_items = user_cart.copy()

    carts[current_user_id] = []

    return jsonify({
        "message": "Payment and checkout successful",
        "payment_id": payment.id,
        "payment_status": payment.status,
        "items": purchased_items,
        "total_amount": total_amount
    })


@app.route("/admin/products", methods=["POST"])
@token_required
def add_product(current_user_id, current_user_role):

    if current_user_role != "admin":
        return jsonify({
            "error": "Admin access required"
        }), 403

    data = request.get_json()

    name = data.get("name")
    price = data.get("price")
    stock = data.get("stock")

    if not name or price is None or stock is None:
        return jsonify({
            "error": "Name, price and stock are required"
        }), 400

    new_product = {
        "id": len(products) + 1,
        "name": name,
        "price": price,
        "stock": stock
    }

    products.append(new_product)

    return jsonify({
        "message": "Product added successfully",
        "product": new_product
    }), 201


@app.route("/admin/products/<int:product_id>", methods=["PUT"])
@token_required
def update_product(
    current_user_id,
    current_user_role,
    product_id
):

    if current_user_role != "admin":
        return jsonify({
            "error": "Admin access required"
        }), 403

    product = None

    for item in products:
        if item["id"] == product_id:
            product = item
            break

    if not product:
        return jsonify({
            "error": "Product not found"
        }), 404

    data = request.get_json()

    if "name" in data:
        product["name"] = data["name"]

    if "price" in data:
        product["price"] = data["price"]

    if "stock" in data:
        product["stock"] = data["stock"]

    return jsonify({
        "message": "Product updated successfully",
        "product": product
    })


@app.route("/admin/products/<int:product_id>", methods=["DELETE"])
@token_required
def delete_product(
    current_user_id,
    current_user_role,
    product_id
):

    if current_user_role != "admin":
        return jsonify({
            "error": "Admin access required"
        }), 403

    for product in products:

        if product["id"] == product_id:

            products.remove(product)

            return jsonify({
                "message": "Product deleted successfully"
            })

    return jsonify({
        "error": "Product not found"
    }), 404


if __name__ == "__main__":
    app.run(debug=True)