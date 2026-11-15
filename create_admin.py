
from getpass import getpass
from werkzeug.security import generate_password_hash
from mysql.connector import IntegrityError, Error

from db_connection import get_db_connection


print("-----------------------------------")
print("       DONORMATCH AI ADMIN")
print("-----------------------------------")

full_name = input("Enter admin name: ").strip()
email = input("Enter admin email: ").strip().lower()
phone = input("Enter admin phone: ").strip()
password = getpass("Create admin password: ")
confirm_password = getpass("Confirm admin password: ")

if not full_name or not email or not phone:
    print("All fields are required.")
    raise SystemExit

if len(password) < 8:
    print("Password must contain at least 8 characters.")
    raise SystemExit

if password != confirm_password:
    print("Passwords do not match.")
    raise SystemExit

connection = None
cursor = None

try:
    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT INTO users
        (full_name, email, phone, password_hash, role)
        VALUES (%s, %s, %s, %s, 'admin')
        """,
        (
            full_name,
            email,
            phone,
            generate_password_hash(password)
        )
    )

    connection.commit()

    print("\nAdmin account created successfully!")
    print("You can now log in using your admin email and password.")

except IntegrityError:
    if connection:
        connection.rollback()
    print("\nThis email is already registered.")
    print("Use a different email address.")

except Error as error:
    if connection:
        connection.rollback()
    print("\nDatabase error:", error)

finally:
    if cursor:
        cursor.close()

    if connection and connection.is_connected():
        connection.close()
