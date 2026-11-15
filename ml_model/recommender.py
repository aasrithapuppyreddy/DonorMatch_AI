
import os
import pandas as pd
import joblib

from datetime import datetime
from ml_model.compatibility import is_compatible

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MODEL_PATH = os.path.join(
    BASE_DIR,
    "donor_recommendation_model.pkl"
)

model = joblib.load(MODEL_PATH)


def get_ranked_donors(cursor, city, urgency, requested_blood_group):

    urgency_values = {
        "normal": 1,
        "urgent": 2,
        "emergency": 3
    }

    urgency_level = urgency_values.get(urgency, 1)

    cursor.execute(
        """
        SELECT
            d.donor_id,
            u.full_name,
            d.blood_group,
            d.city,
            d.area,
            COUNT(dr.response_id) AS total_responses,

            COALESCE(
                SUM(
                    CASE
                        WHEN dr.response = 'accepted' THEN 1
                        ELSE 0
                    END
                ), 0
            ) AS accepted_responses,

            MAX(dr.responded_at) AS last_activity

        FROM donors d

        JOIN users u
            ON d.user_id = u.user_id

        LEFT JOIN donor_responses dr
            ON d.donor_id = dr.donor_id

        WHERE d.available = TRUE
            AND d.consent_to_contact = TRUE
            AND LOWER(d.city) = LOWER(%s)

        GROUP BY
            d.donor_id,
            u.full_name,
            d.blood_group,
            d.city,
            d.area
        """,
        (city,)
    )

    donors = cursor.fetchall()

    # IMPORTANT: Apply blood group compatibility filter first.
    compatible_donors = [
        donor for donor in donors
        if is_compatible(
            donor["blood_group"],
            requested_blood_group
        )
    ]

    if not compatible_donors:
        return []

    model_rows = []

    for donor in compatible_donors:

        total_responses = int(donor["total_responses"] or 0)
        accepted_responses = int(donor["accepted_responses"] or 0)

        if total_responses > 0:
            response_rate = accepted_responses / total_responses
        else:
            response_rate = 0.5

        last_activity = donor["last_activity"]

        if last_activity:
            days_since_activity = max(
                0,
                (datetime.now() - last_activity).days
            )
        else:
            days_since_activity = 365

        model_rows.append({
            "previous_response_rate": response_rate,
            "days_since_last_activity": days_since_activity,
            "urgency_level": urgency_level
        })

    features = pd.DataFrame(
        model_rows,
        columns=[
            "previous_response_rate",
            "days_since_last_activity",
            "urgency_level"
        ]
    )

    probabilities = model.predict_proba(features)

    positive_class_index = list(model.classes_).index(1)

    for index, donor in enumerate(compatible_donors):

        donor["recommendation_score"] = round(
            probabilities[index][positive_class_index] * 100,
            2
        )

    compatible_donors.sort(
        key=lambda donor: donor["recommendation_score"],
        reverse=True
    )

    return compatible_donors
