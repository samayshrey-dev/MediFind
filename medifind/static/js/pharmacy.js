document.addEventListener("DOMContentLoaded", function () {
    const pharmacyMap = document.getElementById("pharmacyMap");
    if (pharmacyMap && typeof L !== "undefined") {
        const lat = parseFloat(pharmacyMap.getAttribute("data-lat")) || 13.0827;
        const lng = parseFloat(pharmacyMap.getAttribute("data-lng")) || 80.2707;
        const name = pharmacyMap.getAttribute("data-name") || "Pharmacy";

        const map = L.map("pharmacyMap").setView([lat, lng], 14);
        L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
            maxZoom: 19,
            attribution: "&copy; OpenStreetMap"
        }).addTo(map);

        const marker = L.marker([lat, lng]).addTo(map);
        marker.bindPopup(`<b>${name}</b><br>Verified Partner Store`);
    }
});