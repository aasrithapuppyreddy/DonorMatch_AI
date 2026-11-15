
import os
from datetime import datetime, date

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from mysql.connector import Error, IntegrityError

from db_connection import get_db_connection
from ml_model.recommender import get_ranked_donors
from ml_model.compatibility import is_compatible


app = Flask(__name__)
app.secret_key = os.environ.get(
    "SECRET_KEY",
    "donormatch-local-development-key"
)


# ==================================================
# COMMON HELPERS
# ==================================================

VALID_BLOOD_GROUPS = [
    "A+", "A-", "B+", "B-",
    "AB+", "AB-", "O+", "O-"
]


def city_key(city):
    """Compare city names without state/country suffixes."""
    return (city or "").split(",")[0].strip().casefold()


def create_notification(user_id, message):
    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            INSERT INTO notifications (user_id, message)
            VALUES (%s, %s)
            """,
            (user_id, message)
        )

        connection.commit()

    except Error as error:
        print("Notification error:", error)

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


def notify_admins(message):
    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            "SELECT user_id FROM users WHERE role = 'admin'"
        )

        admins = cursor.fetchall()

        for admin in admins:
            cursor.execute(
                """
                INSERT INTO notifications (user_id, message)
                VALUES (%s, %s)
                """,
                (admin[0], message)
            )

        connection.commit()

    except Error as error:
        print("Admin notification error:", error)

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


def get_user_notifications(user_id):
    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT *
            FROM notifications
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 30
            """,
            (user_id,)
        )

        notifications = cursor.fetchall()

        cursor.execute(
            """
            SELECT COUNT(*) AS unread_count
            FROM notifications
            WHERE user_id = %s AND is_read = FALSE
            """,
            (user_id,)
        )

        result = cursor.fetchone()
        unread_count = result["unread_count"]

        return notifications, unread_count

    except Error as error:
        print("Loading notifications error:", error)
        return [], 0

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# ==================================================
# TWO-WAY MATCHING AND NOTIFICATIONS
# ==================================================

def notify_donor_about_matching_requests(
    cursor,
    user_id,
    blood_group,
    city,
    available,
    consent
):
    """
    When a donor registers or updates their profile,
    check all existing active compatible requests.
    """

    if not available or not consent:
        return

    cursor.execute(
        """
        SELECT request_id, blood_group, city, urgency
        FROM blood_requests
        WHERE status IN ('pending', 'in_progress')
        """
    )

    existing_requests = cursor.fetchall()

    for blood_request in existing_requests:

        request_id = blood_request[0]
        requested_group = blood_request[1]
        request_city = blood_request[2]

        if city_key(city) != city_key(request_city):
            continue

        if not is_compatible(blood_group, requested_group):
            continue

        message = (
            f"Matching blood request #{request_id}: "
            f"{requested_group} blood needed in {request_city}. "
            f"Please check your dashboard."
        )

        cursor.execute(
            """
            SELECT notification_id
            FROM notifications
            WHERE user_id = %s AND message = %s
            LIMIT 1
            """,
            (user_id, message)
        )

        if cursor.fetchone() is None:
            cursor.execute(
                """
                INSERT INTO notifications (user_id, message)
                VALUES (%s, %s)
                """,
                (user_id, message)
            )


def notify_matching_donors_for_request(
    cursor,
    request_id,
    blood_group,
    city,
    urgency
):
    """
    When a requester creates a new request,
    check all existing eligible donors.
    """

    cursor.execute(
        """
        SELECT donor_id, user_id, blood_group, city,
               available, consent_to_contact
        FROM donors
        """
    )

    donors = cursor.fetchall()

    for donor in donors:

        donor_user_id = donor[1]
        donor_group = donor[2]
        donor_city = donor[3]
        available = donor[4]
        consent = donor[5]

        if not available or not consent:
            continue

        if city_key(donor_city) != city_key(city):
            continue

        if not is_compatible(donor_group, blood_group):
            continue

        message = (
            f"Matching blood request #{request_id}: "
            f"{blood_group} blood needed in {city}. "
            f"Please check your dashboard."
        )

        cursor.execute(
            """
            SELECT notification_id
            FROM notifications
            WHERE user_id = %s AND message = %s
            LIMIT 1
            """,
            (donor_user_id, message)
        )

        if cursor.fetchone() is None:
            cursor.execute(
                """
                INSERT INTO notifications (user_id, message)
                VALUES (%s, %s)
                """,
                (donor_user_id, message)
            )


# ==================================================
# HOME PAGE
# ==================================================

@app.route("/")
def home():
    return render_template("index.html")


# ==================================================
# REGISTRATION
# ==================================================

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        full_name = request.form.get(
            "full_name", ""
        ).strip()

        email = request.form.get(
            "email", ""
        ).strip().lower()

        phone = request.form.get(
            "phone", ""
        ).strip()

        password = request.form.get("password", "")
        role = request.form.get("role", "")

        if not full_name or not email or not phone or not password:
            flash("Please fill in all required fields.", "error")
            return redirect(url_for("register"))

        if role not in ["donor", "requester"]:
            flash("Please select a valid account type.", "error")
            return redirect(url_for("register"))

        password_hash = generate_password_hash(password)

        connection = None
        cursor = None

        try:
            connection = get_db_connection()
            cursor = connection.cursor()

            cursor.execute(
                """
                INSERT INTO users
                (full_name, email, phone, password_hash, role)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    full_name,
                    email,
                    phone,
                    password_hash,
                    role
                )
            )

            user_id = cursor.lastrowid

            if role == "donor":

                blood_group = request.form.get("blood_group")
                age = request.form.get("age")

                city = request.form.get(
                    "city", ""
                ).strip()

                area = request.form.get(
                    "area", ""
                ).strip()

                consent = (
                    request.form.get("consent_to_contact") == "on"
                )

                if blood_group not in VALID_BLOOD_GROUPS:
                    connection.rollback()
                    flash("Please select a valid blood group.", "error")
                    return redirect(url_for("register"))

                try:
                    age = int(age)
                except (TypeError, ValueError):
                    connection.rollback()
                    flash("Please enter a valid age.", "error")
                    return redirect(url_for("register"))

                if age < 18 or age > 100 or not city:
                    connection.rollback()
                    flash("Please check your age and city.", "error")
                    return redirect(url_for("register"))

                cursor.execute(
                    """
                    INSERT INTO donors
                    (user_id, blood_group, age, city, area,
                     available, consent_to_contact)
                    VALUES (%s, %s, %s, %s, %s, TRUE, %s)
                    """,
                    (
                        user_id,
                        blood_group,
                        age,
                        city,
                        area,
                        consent
                    )
                )

                # NEW: Check requests created BEFORE this donor registered.
                notify_donor_about_matching_requests(
                    cursor,
                    user_id,
                    blood_group,
                    city,
                    True,
                    consent
                )

            connection.commit()

            flash(
                "Registration successful! Please log in.",
                "success"
            )

            return redirect(url_for("login"))

        except IntegrityError:
            if connection:
                connection.rollback()

            flash(
                "This email address is already registered.",
                "error"
            )

        except Error as error:
            if connection:
                connection.rollback()

            print("Registration error:", error)
            flash("Registration failed. Please try again.", "error")

        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()

    return render_template("register.html")


# ==================================================
# LOGIN
# ==================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form.get(
            "email", ""
        ).strip().lower()

        password = request.form.get("password", "")

        connection = None
        cursor = None

        try:
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)

            cursor.execute(
                """
                SELECT *
                FROM users
                WHERE email = %s
                """,
                (email,)
            )

            user = cursor.fetchone()

            if user and check_password_hash(
                user["password_hash"], password
            ):

                session.clear()

                session["user_id"] = user["user_id"]
                session["full_name"] = user["full_name"]
                session["email"] = user["email"]
                session["role"] = user["role"]

                if user["role"] == "admin":
                    return redirect(url_for("admin_dashboard"))

                return redirect(url_for("dashboard"))

            flash("Invalid email or password.", "error")

        except Error as error:
            print("Login error:", error)
            flash("Unable to log in. Please try again.", "error")

        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()

    return render_template("login.html")


# ==================================================
# DONOR / REQUESTER DASHBOARD
# ==================================================

@app.route("/dashboard")
def dashboard():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") == "admin":
        return redirect(url_for("admin_dashboard"))

    connection = None
    cursor = None

    my_requests = []
    available_requests = []
    my_responses = []
    recommendations_by_request = {}
    donation_history = []
    total_donations = 0
    donor = None
    notifications = []
    unread_count = 0

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        notifications, unread_count = get_user_notifications(
            session["user_id"]
        )

        if session["role"] == "requester":

            cursor.execute(
                """
                SELECT *
                FROM blood_requests
                WHERE requester_id = %s
                ORDER BY created_at DESC
                """,
                (session["user_id"],)
            )

            my_requests = cursor.fetchall()

            for blood_request in my_requests:

                if blood_request["status"] in [
                    "pending", "in_progress"
                ]:

                    try:
                        ranked_donors = get_ranked_donors(
                            cursor,
                            blood_request["city"],
                            blood_request["urgency"],
                            blood_request["blood_group"]
                        )

                        recommendations_by_request[
                            blood_request["request_id"]
                        ] = ranked_donors

                    except Exception as error:
                        print("Recommendation error:", error)

                        recommendations_by_request[
                            blood_request["request_id"]
                        ] = []

        elif session["role"] == "donor":

            cursor.execute(
                """
                SELECT *
                FROM donors
                WHERE user_id = %s
                """,
                (session["user_id"],)
            )

            donor = cursor.fetchone()

            if donor:

                # Fetch active requests first.
                # Compare city names in Python to handle
                # "Mancherial" and "Mancherial, Telangana, India".
                cursor.execute(
                    """
                    SELECT br.*, u.full_name AS requester_name,
                           u.phone AS requester_phone
                    FROM blood_requests br
                    JOIN users u
                    ON br.requester_id = u.user_id
                    WHERE br.status IN ('pending', 'in_progress')
                    ORDER BY
                        CASE br.urgency
                            WHEN 'emergency' THEN 1
                            WHEN 'urgent' THEN 2
                            ELSE 3
                        END,
                        br.created_at DESC
                    """
                )

                city_requests = cursor.fetchall()

                available_requests = [
                    blood_request
                    for blood_request in city_requests
                    if city_key(donor["city"]) ==
                       city_key(blood_request["city"])
                    and is_compatible(
                        donor["blood_group"],
                        blood_request["blood_group"]
                    )
                ]

                cursor.execute(
                    """
                    SELECT dr.*, br.blood_group, br.city,
                           br.hospital_name, br.urgency
                    FROM donor_responses dr
                    JOIN blood_requests br
                    ON dr.request_id = br.request_id
                    WHERE dr.donor_id = %s
                    ORDER BY dr.response_id DESC
                    """,
                    (donor["donor_id"],)
                )

                my_responses = cursor.fetchall()

                cursor.execute(
                    """
                    SELECT *
                    FROM donation_history
                    WHERE donor_id = %s
                    ORDER BY donation_date DESC
                    """,
                    (donor["donor_id"],)
                )

                donation_history = cursor.fetchall()
                total_donations = len(donation_history)

        else:
            flash("Invalid account role.", "error")
            return redirect(url_for("logout"))

        today_date = date.today().isoformat()

        return render_template(
            "dashboard.html",
            name=session["full_name"],
            donor=donor,
            my_requests=my_requests,
            available_requests=available_requests,
            my_responses=my_responses,
            recommendations_by_request=recommendations_by_request,
            donation_history=donation_history,
            total_donations=total_donations,
            today_date=today_date,
            notifications=notifications,
            unread_count=unread_count
        )

    except Error as error:
        print("Dashboard error:", error)
        flash("Unable to load dashboard.", "error")
        return redirect(url_for("login"))

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# ==================================================
# CREATE BLOOD REQUEST
# ==================================================

@app.route("/create-request", methods=["POST"])
def create_request():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "requester":
        flash("Only requesters can create blood requests.", "error")
        return redirect(url_for("dashboard"))

    blood_group = request.form.get("blood_group")
    units_required = request.form.get("units_required")

    hospital_name = request.form.get(
        "hospital_name", ""
    ).strip()

    city = request.form.get("city", "").strip()

    area = request.form.get("area", "").strip()

    urgency = request.form.get("urgency", "normal")

    required_by = request.form.get("required_by") or None

    if blood_group not in VALID_BLOOD_GROUPS:
        flash("Please select a valid blood group.", "error")
        return redirect(url_for("dashboard"))

    try:
        units_required = int(units_required)
    except (TypeError, ValueError):
        flash("Please enter a valid number of units.", "error")
        return redirect(url_for("dashboard"))

    if units_required < 1 or not hospital_name or not city:
        flash("Please complete all blood request details.", "error")
        return redirect(url_for("dashboard"))

    if urgency not in ["normal", "urgent", "emergency"]:
        urgency = "normal"

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            INSERT INTO blood_requests
            (requester_id, blood_group, units_required,
             hospital_name, city, area, urgency, required_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                session["user_id"],
                blood_group,
                units_required,
                hospital_name,
                city,
                area,
                urgency,
                required_by
            )
        )

        request_id = cursor.lastrowid

        # NEW: Check all donors who registered BEFORE this request.
        notify_matching_donors_for_request(
            cursor,
            request_id,
            blood_group,
            city,
            urgency
        )

        connection.commit()

        notify_admins(
            f"A new {urgency} blood request for {blood_group} "
            f"was created in {city}."
        )

        flash(
            "Blood request created successfully!",
            "success"
        )

    except Error as error:
        if connection:
            connection.rollback()

        print("Create request error:", error)
        flash("Unable to create blood request.", "error")

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

    return redirect(url_for("dashboard"))


# ==================================================
# DONOR ACCEPT / DECLINE REQUEST
# ==================================================

@app.route(
    "/respond-to-request/<int:request_id>",
    methods=["POST"]
)
def respond_to_request(request_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "donor":
        flash("Only donors can respond to blood requests.", "error")
        return redirect(url_for("dashboard"))

    response = request.form.get("response")

    if response not in ["accepted", "declined"]:
        flash("Invalid response.", "error")
        return redirect(url_for("dashboard"))

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT *
            FROM donors
            WHERE user_id = %s
            """,
            (session["user_id"],)
        )

        donor = cursor.fetchone()

        if not donor:
            flash("Donor profile not found.", "error")
            return redirect(url_for("dashboard"))

        if not donor["available"] or not donor["consent_to_contact"]:
            flash(
                "Your donor profile is not available for requests.",
                "error"
            )
            return redirect(url_for("dashboard"))

        cursor.execute(
            """
            SELECT *
            FROM blood_requests
            WHERE request_id = %s
            AND status IN ('pending', 'in_progress')
            """,
            (request_id,)
        )

        blood_request = cursor.fetchone()

        if not blood_request:
            flash(
                "This blood request is no longer active.",
                "error"
            )
            return redirect(url_for("dashboard"))

        if city_key(donor["city"]) != city_key(blood_request["city"]):
            flash(
                "This request is outside your registered city.",
                "error"
            )
            return redirect(url_for("dashboard"))

        if not is_compatible(
            donor["blood_group"],
            blood_request["blood_group"]
        ):
            flash(
                "Your blood group is not compatible with this request.",
                "error"
            )
            return redirect(url_for("dashboard"))

        cursor.execute(
            """
            INSERT INTO donor_responses
            (request_id, donor_id, response, responded_at)
            VALUES (%s, %s, %s, NOW())
            ON DUPLICATE KEY UPDATE
                response = VALUES(response),
                responded_at = NOW()
            """,
            (
                request_id,
                donor["donor_id"],
                response
            )
        )

        cursor.execute(
            """
            INSERT INTO notifications (user_id, message)
            VALUES (%s, %s)
            """,
            (
                blood_request["requester_id"],
                f"A donor has {response} your "
                f"{blood_request['blood_group']} blood request."
            )
        )

        connection.commit()

        flash(
            f"Your response has been {response}.",
            "success"
        )

        notify_admins(
            f"A donor has {response} blood request #{request_id}."
        )

    except Error as error:
        if connection:
            connection.rollback()

        print("Donor response error:", error)
        flash("Unable to submit your response.", "error")

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

    return redirect(url_for("dashboard"))


# ==================================================
# MARK NOTIFICATION AS READ
# ==================================================

@app.route(
    "/notifications/read/<int:notification_id>",
    methods=["POST"]
)
def mark_notification_read(notification_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            UPDATE notifications
            SET is_read = TRUE
            WHERE notification_id = %s
            AND user_id = %s
            """,
            (
                notification_id,
                session["user_id"]
            )
        )

        connection.commit()

        flash(
            "Notification marked as read.",
            "success"
        )

    except Error as error:
        if connection:
            connection.rollback()

        print("Notification error:", error)
        flash("Unable to update notification.", "error")

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

    if session.get("role") == "admin":
        return redirect(url_for("admin_dashboard"))

    return redirect(url_for("dashboard"))


# ==================================================
# ADMIN DASHBOARD
# ==================================================

@app.route("/admin-dashboard")
def admin_dashboard():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "admin":
        flash("Access denied.", "error")
        return redirect(url_for("dashboard"))

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            "SELECT COUNT(*) AS total FROM users"
        )
        total_users = cursor.fetchone()["total"]

        cursor.execute(
            "SELECT COUNT(*) AS total FROM donors"
        )
        total_donors = cursor.fetchone()["total"]

        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM users
            WHERE role = 'requester'
            """
        )
        total_requesters = cursor.fetchone()["total"]

        cursor.execute(
            "SELECT COUNT(*) AS total FROM blood_requests"
        )
        total_requests = cursor.fetchone()["total"]

        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM blood_requests
            WHERE status = 'pending'
            """
        )
        pending_requests = cursor.fetchone()["total"]

        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM donor_responses
            WHERE response = 'accepted'
            """
        )
        accepted_responses = cursor.fetchone()["total"]

        cursor.execute(
            """
            SELECT user_id, full_name, email, phone, role, created_at
            FROM users
            ORDER BY created_at DESC
            LIMIT 10
            """
        )
        recent_users = cursor.fetchall()

        cursor.execute(
            """
            SELECT br.*, u.full_name AS requester_name,
                   u.phone AS requester_phone
            FROM blood_requests br
            JOIN users u ON br.requester_id = u.user_id
            ORDER BY br.created_at DESC
            LIMIT 50
            """
        )
        all_requests = cursor.fetchall()

        notifications, unread_count = get_user_notifications(
            session["user_id"]
        )

        return render_template(
            "admin_dashboard.html",
            name=session["full_name"],
            total_users=total_users,
            total_donors=total_donors,
            total_requesters=total_requesters,
            total_requests=total_requests,
            pending_requests=pending_requests,
            accepted_responses=accepted_responses,
            recent_users=recent_users,
            all_requests=all_requests,
            notifications=notifications,
            unread_count=unread_count
        )

    except Error as error:
        print("Admin dashboard error:", error)
        flash("Unable to load admin dashboard.", "error")
        return redirect(url_for("login"))

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# ==================================================
# ADMIN UPDATE REQUEST STATUS
# ==================================================

@app.route(
    "/admin/update-request/<int:request_id>",
    methods=["POST"]
)
def admin_update_request(request_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "admin":
        flash("Access denied.", "error")
        return redirect(url_for("dashboard"))

    new_status = request.form.get("status")

    valid_statuses = [
        "pending",
        "in_progress",
        "fulfilled",
        "cancelled"
    ]

    if new_status not in valid_statuses:
        flash("Invalid request status.", "error")
        return redirect(url_for("admin_dashboard"))

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            UPDATE blood_requests
            SET status = %s
            WHERE request_id = %s
            """,
            (new_status, request_id)
        )

        connection.commit()

        flash(
            "Blood request status updated successfully.",
            "success"
        )

    except Error as error:
        if connection:
            connection.rollback()

        print("Admin update error:", error)
        flash("Unable to update request status.", "error")

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

    return redirect(url_for("admin_dashboard"))


# ==================================================
# UPDATE DONOR PROFILE
# ==================================================

@app.route("/update-donor-profile", methods=["POST"])
def update_donor_profile():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "donor":
        flash(
            "Only donors can update donor profiles.",
            "error"
        )
        return redirect(url_for("dashboard"))

    blood_group = request.form.get("blood_group")

    city = request.form.get(
        "city", ""
    ).strip()

    area = request.form.get(
        "area", ""
    ).strip()

    available = (
        request.form.get("available") == "on"
    )

    consent = (
        request.form.get("consent_to_contact") == "on"
    )

    if blood_group not in VALID_BLOOD_GROUPS or not city:
        flash(
            "Please enter valid donor profile details.",
            "error"
        )
        return redirect(url_for("dashboard"))

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            UPDATE donors
            SET blood_group = %s,
                city = %s,
                area = %s,
                available = %s,
                consent_to_contact = %s
            WHERE user_id = %s
            """,
            (
                blood_group,
                city,
                area,
                available,
                consent,
                session["user_id"]
            )
        )

        cursor.execute(
            """
            SELECT donor_id
            FROM donors
            WHERE user_id = %s
            """,
            (session["user_id"],)
        )

        donor = cursor.fetchone()

        if donor:
            # NEW: Check existing requests after profile update.
            notify_donor_about_matching_requests(
                cursor,
                session["user_id"],
                blood_group,
                city,
                available,
                consent
            )

        connection.commit()

        flash(
            "Donor profile updated successfully. "
            "Matching requests have been checked.",
            "success"
        )

    except Error as error:
        if connection:
            connection.rollback()

        print("Profile update error:", error)
        flash("Unable to update donor profile.", "error")

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

    return redirect(url_for("dashboard"))


# ==================================================
# ADD DONATION HISTORY
# ==================================================

@app.route("/add-donation", methods=["POST"])
def add_donation():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "donor":
        flash(
            "Only donors can add donation history.",
            "error"
        )
        return redirect(url_for("dashboard"))

    donation_date = request.form.get("donation_date")

    hospital_name = request.form.get(
        "hospital_name", ""
    ).strip()

    try:
        parsed_date = datetime.strptime(
            donation_date,
            "%Y-%m-%d"
        ).date()

        if parsed_date > date.today():
            flash(
                "Donation date cannot be in the future.",
                "error"
            )
            return redirect(url_for("dashboard"))

    except (TypeError, ValueError):
        flash(
            "Please enter a valid donation date.",
            "error"
        )
        return redirect(url_for("dashboard"))

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT donor_id
            FROM donors
            WHERE user_id = %s
            """,
            (session["user_id"],)
        )

        donor = cursor.fetchone()

        if not donor:
            flash("Donor profile not found.", "error")
            return redirect(url_for("dashboard"))

        cursor.execute(
            """
            INSERT INTO donation_history
            (donor_id, donation_date, hospital_name)
            VALUES (%s, %s, %s)
            """,
            (
                donor[0],
                parsed_date,
                hospital_name
            )
        )

        connection.commit()

        flash(
            "Donation history added successfully.",
            "success"
        )

    except Error as error:
        if connection:
            connection.rollback()

        print("Donation history error:", error)
        flash("Unable to add donation history.", "error")

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

    return redirect(url_for("dashboard"))


# ==================================================
# LOGOUT
# ==================================================

@app.route("/logout")
def logout():

    session.clear()

    flash(
        "You have been logged out successfully.",
        "success"
    )

    return redirect(url_for("home"))


# ==================================================
# RUN APPLICATION
# ==================================================

if __name__ == "__main__":
    app.run(debug=True)
