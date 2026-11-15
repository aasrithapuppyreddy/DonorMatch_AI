
document.addEventListener("DOMContentLoaded", function () {

    // Donor and requester selection
    const roleSelect = document.getElementById("role");
    const donorFields = document.getElementById("donor-fields");

    if (roleSelect && donorFields) {

        function toggleDonorFields() {

            if (roleSelect.value === "donor") {
                donorFields.style.display = "block";

                donorFields.querySelectorAll("input, select").forEach(function (field) {
                    if (field.name === "blood_group" ||
                        field.name === "age" ||
                        field.name === "city") {
                        field.required = true;
                    }
                });

            } else {
                donorFields.style.display = "none";

                donorFields.querySelectorAll("input, select").forEach(function (field) {
                    field.required = false;
                });
            }
        }

        roleSelect.addEventListener("change", toggleDonorFields);

        toggleDonorFields();
    }

    // Smooth scrolling for homepage section links
    document.querySelectorAll('a[href^="#"]').forEach(function (link) {

        link.addEventListener("click", function (event) {

            const targetId = this.getAttribute("href");

            if (targetId && targetId.length > 1) {
                const target = document.querySelector(targetId);

                if (target) {
                    event.preventDefault();

                    target.scrollIntoView({
                        behavior: "smooth"
                    });
                }
            }
        });
    });

});
