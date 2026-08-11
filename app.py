from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, render_template, request, redirect, url_for, session
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for,flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from dotenv import load_dotenv
import os
import stripe

load_dotenv()  # Load environment variables from .env file

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
app.secret_key = os.getenv("FLASK_SECRET_KEY")
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PUBLIC_KEY = os.getenv("STRIPE_PUBLIC_KEY")
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///lasu_hotel.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ---------- MODELS ----------

class Room(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    image = db.Column(db.String(100), nullable=False)
    desc = db.Column(db.String(300), nullable=False)

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True)
    name= db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey('room.id'), nullable=False)
    checkin = db.Column(db.String(20), nullable=False)
    checkout = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default="Pending")
    payment_status = db.Column(db.String(20), default="Unpaid")
    stripe_session_id = db.Column(db.String(200), nullable=True)
    room = db.relationship('Room', backref='bookings')

# ---------- ROUTES ----------
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/rooms")
def rooms_page():
    rooms = Room.query.all()
    return render_template("rooms.html", rooms=rooms)
@app.route("/booking", methods=["GET", "POST"])
def booking():
    rooms = Room.query.all()

    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        room_id = request.form.get("room_id")
        checkin = request.form.get("checkin")
        checkout = request.form.get("checkout")

        print("DEBUG FORM DATA:", name, email, room_id, checkin, checkout)

        room = Room.query.get(room_id)

        new_booking = Booking(
            customer_id=session.get("customer_id"),
            name=name,
            email=email,
            room_id=room_id,
            checkin=checkin,
            checkout=checkout
        )
        db.session.add(new_booking)
        db.session.commit()

        checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": room.name},
                    "unit_amount": int(room.price * 100),
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=url_for("payment_success", booking_id=new_booking.id, _external=True),
            cancel_url=url_for("payment_cancelled", booking_id=new_booking.id, _external=True),
        )

        new_booking.stripe_session_id = checkout_session.id
        db.session.commit()

        return redirect(checkout_session.url, code=303)

    # GET request — show the booking form
    room_id = request.args.get("room_id")
    customer = None
    if session.get("customer_id"):
        customer = Customer.query.get(session["customer_id"])

    return render_template("booking.html", rooms=rooms, selected_room=room_id, customer=customer)

@app.route("/booking-success")
def booking_success():
    return render_template("booking_success.html")
@app.route("/payment-success/<int:booking_id>")
def payment_success(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    booking.payment_status = "Paid"
    db.session.commit()
    return render_template("booking_success.html")
@app.route("/signup", methods=["GET", "POST"])
def signup():
    error = None
    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        password = request.form.get("password")

        if Customer.query.filter_by(email=email).first():
            error = "An account with that email already exists."
        else:
            new_customer = Customer(name=name, email=email)
            new_customer.set_password(password)
            db.session.add(new_customer)
            db.session.commit()
            session["customer_id"] = new_customer.id
            return redirect(url_for("home"))

    return render_template("signup.html", error=error)

@app.route("/login", methods=["GET", "POST"])
def customer_login():
    error = None
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        customer = Customer.query.filter_by(email=email).first()

        if customer and customer.check_password(password):
            session["customer_id"] = customer.id
            return redirect(url_for("home"))
        error = "Invalid email or password."

    return render_template("customer_login.html", error=error)

@app.route("/logout")
def customer_logout():
    session.pop("customer_id", None)
    return redirect(url_for("home"))

@app.route("/my-bookings")
def my_bookings():
    if not session.get("customer_id"):
        return redirect(url_for("customer_login"))
    customer = Customer.query.get(session["customer_id"])
    return render_template("my_bookings.html", customer=customer)

@app.route("/payment-cancelled/<int:booking_id>")
def payment_cancelled(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    booking.payment_status = "Cancelled"
    db.session.commit()
    return render_template("payment_cancelled.html")
@app.route("/admin")
def admin_dashboard():
    bookings = Booking.query.order_by(Booking.created_at.desc()).all()
    total_bookings = len(bookings)
    confirmed = [b for b in bookings if b.status == "Confirmed"]
    pending = [b for b in bookings if b.status == "Pending"]
    revenue = sum(b.room.price for b in confirmed)

    stats = {
        "total_bookings": total_bookings,
        "confirmed_count": len(confirmed),
        "pending_count": len(pending),
        "revenue": revenue
    }

    return render_template("admin.html", bookings=bookings, stats=stats)
@login_required

@app.route("/admin/booking/<int:booking_id>/confirm")
def confirm_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    booking.status = "Confirmed"
    db.session.commit()
    return redirect(url_for("admin_dashboard"))
@login_required
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("admin_dashboard"))
        error = "Invalid username or password"
    return render_template("admin_login.html", error=error)

@app.route("/admin/logout")
def admin_logout():
    session.pop("logged_in", None)
    return redirect(url_for("admin_login"))

@login_required
@app.route("/admin/booking/<int:booking_id>/cancel")
def cancel_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    booking.status = "Cancelled"
    db.session.commit()
    return redirect(url_for("admin_dashboard"))
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated_function


# ---------- DB SETUP ----------

def seed_rooms():
    if Room.query.count() == 0:
        rooms = [
            Room(name="Deluxe Ocean View", price=120, image="room-deluxe.jpg",
                 desc="Spacious room with a private balcony overlooking the sea."),
            Room(name="Beachfront Suite", price=220, image="room-suite.jpg",
                 desc="Luxury suite steps away from the shoreline."),
            Room(name="Standard Garden Room", price=80, image="room-standard.jpg",
                 desc="Cozy and affordable, surrounded by tropical gardens."),
        ]
        db.session.bulk_save_objects(rooms)
        db.session.commit()

with app.app_context():
    db.create_all()
    seed_rooms()
    @app.errorhandler(404)
    def not_found(e):
     return render_template("404.html"), 404

@app.errorhandler(500)
def server_error(e):
    return render_template("500.html"), 500

if __name__ == "__main__":
    app.run(debug=True)