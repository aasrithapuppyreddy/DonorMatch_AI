
import mysql.connector

def get_db_connection():
    connection = mysql.connector.connect(
        host="localhost",
        user="root",
        password="Root@123",
        database="donormatch_db"
    )

    return connection


if __name__ == "__main__":
    try:
        conn = get_db_connection()
        print("SUCCESS! Connected to DonorMatch AI database.")

        cursor = conn.cursor()
        cursor.execute("SHOW TABLES")

        print("\nAvailable tables:")
        for table in cursor.fetchall():
            print(table[0])

        cursor.close()
        conn.close()

    except mysql.connector.Error as error:
        print("Database connection failed:", error)
