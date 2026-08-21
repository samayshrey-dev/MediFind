// MedFinder Universal Map Controller with Blue (Open) / Red (Closed) Pins
(function () {
  'use strict';

  const mapDiv = document.getElementById("map");
  if (!mapDiv) return;

  function createPin(isOpen) {
    const pinColor = isOpen ? '#2563eb' : '#ef4444';
    const shadowColor = isOpen ? 'rgba(37, 99, 235, 0.35)' : 'rgba(239, 68, 68, 0.35)';
    const iconName = isOpen ? 'fa-hospital' : 'fa-door-closed';

    const html = `
      <div style="position: relative; width: 32px; height: 40px; display: flex; flex-direction: column; align-items: center; cursor: pointer;">
        <div style="width: 30px; height: 30px; border-radius: 50% 50% 50% 0; transform: rotate(-45deg); background: ${pinColor}; border: 2px solid #ffffff; box-shadow: 0 4px 10px ${shadowColor}; display: flex; align-items: center; justify-content: center;">
          <div style="transform: rotate(45deg); color: #ffffff; font-size: 11px;">
            <i class="fa-solid ${iconName}"></i>
          </div>
        </div>
        <div style="width: 6px; height: 3px; border-radius: 50%; background: rgba(0,0,0,0.3); margin-top: -1px;"></div>
      </div>
    `;

    return L.divIcon({
      html: html,
      className: 'custom-pharmacy-pin',
      iconSize: [32, 40],
      iconAnchor: [16, 38],
      popupAnchor: [0, -36]
    });
  }

  function createUserPin() {
    const html = `
      <div style="position: relative; width: 34px; height: 34px; display: flex; align-items: center; justify-content: center;">
        <div style="position: absolute; width: 34px; height: 34px; border-radius: 50%; background: rgba(16, 185, 129, 0.3); animation: userPulse 2s infinite ease-out;"></div>
        <div style="width: 16px; height: 16px; border-radius: 50%; background: #10b981; border: 2.5px solid #ffffff; box-shadow: 0 2px 8px rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center;">
          <div style="width: 5px; height: 5px; border-radius: 50%; background: #ffffff;"></div>
        </div>
      </div>
    `;

    return L.divIcon({
      html: html,
      className: 'custom-user-pin',
      iconSize: [34, 34],
      iconAnchor: [17, 17],
      popupAnchor: [0, -18]
    });
  }

  const map = L.map("map").setView([13.0827, 80.2707], 12);

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap"
  }).addTo(map);

  const bounds = [];
  let userMarker = null;

  // Request & Redirect to User Location
  function locateUser(flyTo = true) {
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(function (position) {
        const lat = position.coords.latitude;
        const lng = position.coords.longitude;

        if (userMarker) map.removeLayer(userMarker);
        userMarker = L.marker([lat, lng], { icon: createUserPin() })
          .addTo(map)
          .bindPopup("<strong><i class='fa-solid fa-location-dot text-success me-1'></i> Your Location</strong>");

        bounds.push([lat, lng]);

        if (flyTo) {
          map.flyTo([lat, lng], 14, { duration: 1.2 });
        }
      });
    }
  }

  // Bind Locate Me button if present
  const locateBtn = document.getElementById("locateMeBtn");
  if (locateBtn) {
    locateBtn.addEventListener("click", () => locateUser(true));
  }

  let currentMarkers = [];

  function updatePharmacyMarkers(dataList) {
    if (!map) return;
    
    // Clear existing pharmacy markers
    currentMarkers.forEach(m => map.removeLayer(m));
    currentMarkers = [];
    const markerBounds = [];

    if (userMarker) {
      markerBounds.push(userMarker.getLatLng());
    }

    if (Array.isArray(dataList)) {
      dataList.forEach(function (item) {
        const lat = parseFloat(item.latitude || item.pharmacy_lat || item.lat);
        const lng = parseFloat(item.longitude || item.pharmacy_lng || item.lng);

        if (!isNaN(lat) && !isNaN(lng)) {
          const isOpen = item.is_open !== undefined ? item.is_open : true;
          const pharmName = item.pharmacy_name || item.pharmacy || item.name || 'Partner Pharmacy';
          const pharmAddress = item.pharmacy_address || item.address || '';
          const pharmCity = item.pharmacy_city || item.city || '';
          const medName = item.medicine_name || item.medicine || '';
          const price = item.price !== undefined ? parseFloat(item.price).toFixed(2) : null;
          const distance = item.distance_km !== undefined && item.distance_km !== null ? `${item.distance_km} km away` : '';

          const popup = `
            <div style="font-family: var(--font-sans); min-width: 190px;">
              <div class="d-flex align-items-center gap-1 mb-1">
                <span class="badge ${isOpen ? 'bg-primary' : 'bg-danger'} px-2 py-1" style="font-size: 0.7rem;">
                  ● ${isOpen ? 'Open Store' : 'Closed'}
                </span>
                ${distance ? `<span class="badge bg-light text-muted border px-2 py-1" style="font-size: 0.7rem;">${distance}</span>` : ''}
              </div>
              <strong style="font-size: 0.9rem;">${pharmName}</strong><br>
              <span class="text-muted small">${pharmAddress} ${pharmCity}</span>
              ${medName ? `<div class="mt-1 small"><strong>${medName}</strong>: <span class="text-success fw-bold">₹${price}</span></div>` : ''}
              <div class="mt-2 pt-1 border-top">
                <a target="_blank" href="https://www.google.com/maps/dir/?api=1&destination=${lat},${lng}" class="btn btn-sm btn-outline-secondary w-100 py-1" style="font-size: 0.75rem;">
                  🧭 Get Directions
                </a>
              </div>
            </div>
          `;

          const m = L.marker([lat, lng], { icon: createPin(isOpen) })
            .addTo(map)
            .bindPopup(popup);

          currentMarkers.push(m);
          markerBounds.push([lat, lng]);
        }
      });
    }

    if (markerBounds.length > 0) {
      map.fitBounds(markerBounds, { padding: [40, 40], maxZoom: 15 });
    }
  }

  // Load initial markers if available
  const initialData = typeof pharmacyData !== "undefined" ? pharmacyData : (window.MEDIFIND_MARKERS || []);
  if (Array.isArray(initialData) && initialData.length > 0) {
    updatePharmacyMarkers(initialData);
  }

  locateUser(false);

  window.MedFinderMap = {
    updateMarkers: updatePharmacyMarkers,
    locateUser: locateUser,
    map: map
  };
})();