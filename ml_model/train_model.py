
import pandas as pd
import matplotlib.pyplot as plt

from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    classification_report,
    ConfusionMatrixDisplay
)

import joblib
import os


print("------------------------------------")
print(" DONORMATCH AI - MODEL EVALUATION")
print("------------------------------------")


# 1. LOAD DATASET

data = pd.read_csv("ml_model/donor_training_data.csv")

print("\nDataset loaded successfully!")
print("Dataset shape:", data.shape)


# 2. SELECT FEATURES AND TARGET

X = data[
    [
        "previous_response_rate",
        "days_since_last_activity",
        "urgency_level"
    ]
]

y = data["responded"]


# 3. SPLIT DATASET

X_train, X_test, y_train, y_test = train_test_split(
    X,
    y,
    test_size=0.25,
    random_state=42,
    stratify=y
)

print("\nTraining records:", len(X_train))
print("Testing records:", len(X_test))


# 4. TRAIN RANDOM FOREST MODEL

model = RandomForestClassifier(
    n_estimators=100,
    max_depth=5,
    random_state=42,
    class_weight="balanced"
)

model.fit(X_train, y_train)

print("\nModel training completed!")


# 5. MAKE PREDICTIONS

y_pred = model.predict(X_test)


# 6. EVALUATE MODEL

accuracy = accuracy_score(y_test, y_pred)

precision = precision_score(
    y_test, y_pred, zero_division=0
)

recall = recall_score(
    y_test, y_pred, zero_division=0
)

f1 = f1_score(
    y_test, y_pred, zero_division=0
)


print("\n------------------------------------")
print(" MODEL PERFORMANCE")
print("------------------------------------")

print(f"Accuracy  : {accuracy * 100:.2f}%")
print(f"Precision : {precision * 100:.2f}%")
print(f"Recall    : {recall * 100:.2f}%")
print(f"F1 Score  : {f1 * 100:.2f}%")


# 7. CLASSIFICATION REPORT

print("\nClassification Report:")
print(classification_report(
    y_test,
    y_pred,
    zero_division=0
))


# 8. CONFUSION MATRIX

ConfusionMatrixDisplay.from_predictions(
    y_test,
    y_pred,
    display_labels=["Not Responded", "Responded"]
)

plt.title("DonorMatch AI - Confusion Matrix")
plt.tight_layout()
plt.savefig("ml_model/confusion_matrix.png")
plt.show()


# 9. FEATURE IMPORTANCE

importance = pd.DataFrame({
    "Feature": X.columns,
    "Importance": model.feature_importances_
})

importance = importance.sort_values(
    by="Importance",
    ascending=False
)

print("\nFeature Importance:")
print(importance)


importance.plot(
    x="Feature",
    y="Importance",
    kind="bar",
    legend=False,
    title="DonorMatch AI - Feature Importance"
)

plt.ylabel("Importance Score")
plt.tight_layout()
plt.savefig("ml_model/feature_importance.png")
plt.show()


# 10. SAVE TRAINED MODEL

joblib.dump(
    model,
    "ml_model/donor_recommendation_model.pkl"
)

print("\nUpdated model saved successfully!")

print("\nEvaluation completed!")
