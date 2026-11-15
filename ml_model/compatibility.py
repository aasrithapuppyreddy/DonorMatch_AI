
# Red blood cell donor compatibility rules.
# Key = recipient blood group
# Values = blood groups that may donate red blood cells to that recipient.

RBC_COMPATIBILITY = {
    "A+": ["A+", "A-", "O+", "O-"],
    "A-": ["A-", "O-"],
    "B+": ["B+", "B-", "O+", "O-"],
    "B-": ["B-", "O-"],
    "AB+": ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"],
    "AB-": ["A-", "B-", "AB-", "O-"],
    "O+": ["O+", "O-"],
    "O-": ["O-"]
}


def is_compatible(donor_blood_group, recipient_blood_group):
    """
    Preliminary red blood cell compatibility check.
    Returns True when the donor group is listed as compatible
    with the recipient group.
    """

    compatible_groups = RBC_COMPATIBILITY.get(
        recipient_blood_group, []
    )

    return donor_blood_group in compatible_groups
