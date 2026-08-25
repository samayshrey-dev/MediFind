/**
 * Medifind AI — Prescription OCR & Inventory Search Client Engine
 * Pipeline: File Upload -> POST /api/ai/prescription/analyze/ -> Confirmation Matrix -> Inventory Search -> Leaflet Sync
 */
(function () {
  'use strict';

  let currentPrescriptionId = null;
  let extractedItems = [];
  let userCoords = { lat: 13.0827, lng: 80.2707 };

  if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        userCoords = { lat: pos.coords.latitude, lng: pos.coords.longitude };
      },
      () => {},
      { timeout: 4000 }
    );
  }

  // DOM Element Handles
  const fileInput = document.getElementById('prescriptionFileInput');
  const dropZone = document.getElementById('dropZone');
  const errorMsg = document.getElementById('uploadErrorMsg');

  const stepUploadCard = document.getElementById('stepUploadCard');
  const stepProcessingCard = document.getElementById('stepProcessingCard');
  const stepConfirmationCard = document.getElementById('stepConfirmationCard');
  const stepResultsContainer = document.getElementById('stepResultsContainer');

  const confirmationTableBody = document.getElementById('confirmationTableBody');
  const btnConfirmAndSearch = document.getElementById('btnConfirmAndSearch');
  const btnAddManualMedicineBtn = document.getElementById('btnAddManualMedicineBtn');
  const btnRestartUpload = document.getElementById('btnRestartUpload');

  if (!fileInput || !dropZone) return;

  // File Upload Handlers
  fileInput.addEventListener('change', handleFileSelect);

  ['dragenter', 'dragover'].forEach(evt => {
    dropZone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropZone.classList.add('border-primary', 'bg-primary-subtle');
    });
  });

  ['dragleave', 'drop'].forEach(evt => {
    dropZone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropZone.classList.remove('border-primary', 'bg-primary-subtle');
    });
  });

  dropZone.addEventListener('drop', (e) => {
    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      fileInput.files = files;
      handleFileSelect();
    }
  });

  function showError(msg) {
    if (errorMsg) {
      errorMsg.innerText = msg;
      errorMsg.classList.remove('d-none');
    }
  }

  function hideError() {
    if (errorMsg) {
      errorMsg.classList.add('d-none');
    }
  }

  // STEP 1 -> STEP 2: Analyze Prescription
  async function handleFileSelect() {
    hideError();
    const file = fileInput.files[0];
    if (!file) return;

    // Client-side quick size check
    if (file.size > 10 * 1024 * 1024) {
      showError('File exceeds 10MB limit. Please upload a smaller image.');
      return;
    }

    // Show processing indicator
    stepUploadCard.classList.add('d-none');
    stepProcessingCard.classList.remove('d-none');

    const formData = new FormData();
    formData.append('prescription_file', file);

    try {
      const res = await fetch('/api/ai/prescription/analyze/', {
        method: 'POST',
        body: formData
      });

      const rawText = await res.text();
      let data;
      try {
        data = JSON.parse(rawText);
      } catch (e) {
        throw new Error('Server returned an invalid response. Please check image format or try again.');
      }

      if (!res.ok || !data.success) {
        throw new Error(data.message || 'Prescription analysis failed.');
      }

      currentPrescriptionId = data.prescription_id;
      extractedItems = data.extracted_medicines || [];

      // Transition to STEP 3 Confirmation
      stepProcessingCard.classList.add('d-none');
      stepConfirmationCard.classList.remove('d-none');
      renderConfirmationTable(extractedItems);

    } catch (err) {
      console.error('Prescription OCR error:', err);
      stepProcessingCard.classList.add('d-none');
      stepUploadCard.classList.remove('d-none');
      showError(err.message || 'Could not analyze prescription. Please ensure text is legible.');
    }
  }

  // Render Extracted Medicines Confirmation Matrix
  function renderConfirmationTable(items) {
    if (!confirmationTableBody) return;

    if (!items || items.length === 0) {
      confirmationTableBody.innerHTML = `
        <tr>
          <td colspan="5" class="text-center py-4 text-muted">
            <i class="fa-solid fa-circle-exclamation text-warning mb-1 fs-4 d-block"></i>
            No medicines automatically identified. Click "Add Medicine" to enter manually.
          </td>
        </tr>
      `;
      return;
    }

    confirmationTableBody.innerHTML = items.map((item, idx) => {
      const bestMatchName = item.best_match ? item.best_match.name : item.extracted_name;
      const bestMatchId = item.best_match ? item.best_match.id : '';

      let badgeClass = 'bg-success-subtle text-success border border-success-subtle';
      let badgeIcon = 'fa-circle-check';
      let badgeLabel = 'Exact Match';

      if (item.confidence_category === 'MEDIUM' || item.match_type === 'partial') {
        badgeClass = 'bg-info-subtle text-info-emphasis border border-info-subtle';
        badgeIcon = 'fa-magnifying-glass';
        badgeLabel = 'Fuzzy Match';
      } else if (item.confidence_category === 'LOW' || !item.best_match) {
        badgeClass = 'bg-warning-subtle text-warning-emphasis border border-warning-subtle';
        badgeIcon = 'fa-triangle-exclamation';
        badgeLabel = 'Review Needed';
      }

      return `
        <tr data-index="${idx}">
          <td>
            <input type="hidden" class="row-med-id" value="${bestMatchId}">
            <input type="text" class="form-control form-control-sm fw-bold text-dark row-med-name" value="${bestMatchName || ''}" placeholder="Medicine name">
            <small class="text-muted d-block mt-0.5" style="font-size: 0.72rem;">Raw OCR: "${item.raw_text}"</small>
          </td>
          <td>
            <input type="text" class="form-control form-control-sm row-med-strength" value="${item.strength || ''}" placeholder="e.g. 650 mg">
          </td>
          <td>
            <input type="text" class="form-control form-control-sm row-med-freq" value="${item.frequency || '1-0-1'}" placeholder="e.g. 1-0-1">
          </td>
          <td>
            <span class="badge ${badgeClass} rounded-pill px-2.5 py-1 small">
              <i class="fa-solid ${badgeIcon} me-1"></i> ${badgeLabel}
            </span>
          </td>
          <td class="text-center">
            <button type="button" class="btn btn-sm btn-light text-danger rounded-circle btn-remove-row" title="Remove">
              <i class="fa-solid fa-trash-can"></i>
            </button>
          </td>
        </tr>
      `;
    }).join('');

    // Attach row remove handlers
    confirmationTableBody.querySelectorAll('.btn-remove-row').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const tr = e.target.closest('tr');
        if (tr) tr.remove();
      });
    });
  }

  function addMedicineRow(name = '', strength = '500 mg', freq = '1-0-1') {
    if (!confirmationTableBody) return;

    // Clear empty table warning row if present
    const emptyRow = confirmationTableBody.querySelector('td[colspan]');
    if (emptyRow) {
      emptyRow.closest('tr').remove();
    }

    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>
        <input type="hidden" class="row-med-id" value="">
        <input type="text" class="form-control form-control-sm fw-bold text-dark row-med-name" value="${name}" placeholder="e.g. Amaryl / Paracetamol">
        <small class="text-muted d-block mt-0.5" style="font-size: 0.72rem;">User selected / added</small>
      </td>
      <td>
        <input type="text" class="form-control form-control-sm row-med-strength" value="${strength}" placeholder="e.g. 500 mg">
      </td>
      <td>
        <input type="text" class="form-control form-control-sm row-med-freq" value="${freq}" placeholder="e.g. 1-0-1">
      </td>
      <td>
        <span class="badge bg-secondary-subtle text-secondary rounded-pill px-2.5 py-1 small">Manual</span>
      </td>
      <td class="text-center">
        <button type="button" class="btn btn-sm btn-light text-danger rounded-circle btn-remove-row" title="Remove">
          <i class="fa-solid fa-trash-can"></i>
        </button>
      </td>
    `;
    tr.querySelector('.btn-remove-row').addEventListener('click', () => tr.remove());
    confirmationTableBody.appendChild(tr);
  }

  // Manual Add Medicine Button
  if (btnAddManualMedicineBtn) {
    btnAddManualMedicineBtn.addEventListener('click', () => addMedicineRow('', '500 mg', '1-0-1'));
  }

  // Quick Medicine Preset Chips
  document.querySelectorAll('.quick-med-chip').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const target = e.currentTarget;
      const name = target.dataset.name || '';
      const strength = target.dataset.strength || '';
      const freq = target.dataset.freq || '1-0-1';
      addMedicineRow(name, strength, freq);
    });
  });

  if (btnRestartUpload) {
    btnRestartUpload.addEventListener('click', () => {
      fileInput.value = '';
      stepConfirmationCard.classList.add('d-none');
      stepResultsContainer.classList.add('d-none');
      stepUploadCard.classList.remove('d-none');
    });
  }

  // STEP 3 -> STEP 4: Confirm & Search Inventory
  if (btnConfirmAndSearch) {
    btnConfirmAndSearch.addEventListener('click', async () => {
      const rows = confirmationTableBody.querySelectorAll('tr');
      const confirmedMeds = [];

      rows.forEach(tr => {
        const medId = tr.querySelector('.row-med-id')?.value;
        const name = tr.querySelector('.row-med-name')?.value?.trim();
        const strength = tr.querySelector('.row-med-strength')?.value?.trim();
        const freq = tr.querySelector('.row-med-freq')?.value?.trim();

        if (name) {
          confirmedMeds.push({
            medicine_id: medId ? parseInt(medId) : None,
            name: name,
            strength: strength,
            frequency: freq
          });
        }
      });

      if (confirmedMeds.length === 0) {
        alert('Please confirm at least one medicine to search inventory.');
        return;
      }

      btnConfirmAndSearch.disabled = true;
      btnConfirmAndSearch.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin me-2"></i> Searching Pharmacies...';

      try {
        // 1. Save confirmation
        if (currentPrescriptionId) {
          await fetch('/api/ai/prescription/confirm/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              prescription_id: currentPrescriptionId,
              confirmed_medicines: confirmedMeds
            })
          });
        }

        // 2. Perform Inventory Search
        const searchRes = await fetch('/api/ai/prescription/find-medicines/', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            prescription_id: currentPrescriptionId,
            confirmed_medicines: confirmedMeds,
            latitude: userCoords.lat,
            longitude: userCoords.lng,
            radius_km: 5.0
          })
        });

        const data = await searchRes.json();
        if (!searchRes.ok || !data.success) {
          throw new Error(data.message || 'Inventory lookup failed.');
        }

        // Render Results
        renderPharmacyResults(data);
        stepConfirmationCard.classList.add('d-none');
        stepResultsContainer.classList.remove('d-none');

      } catch (err) {
        console.error('Inventory search error:', err);
        alert(err.message || 'Error checking pharmacy inventory.');
      } finally {
        btnConfirmAndSearch.disabled = false;
        btnConfirmAndSearch.innerHTML = '<i class="fa-solid fa-magnifying-glass-location me-2"></i> Confirm & Search Inventory';
      }
    });
  }

  // Render Ranked Pharmacy Results
  function renderPharmacyResults(data) {
    const list = document.getElementById('prescriptionPharmacyList');
    const aiText = document.getElementById('prescriptionAiText');
    const aiSummary = document.getElementById('prescriptionFulfillmentSummary');

    if (aiText) {
      aiText.innerHTML = (data.ai_explanation || '').replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    }
    if (aiSummary) {
      aiSummary.innerText = `Searching ${data.total_medicines} confirmed medicines`;
    }

    if (!list) return;

    if (!data.pharmacies || data.pharmacies.length === 0) {
      list.innerHTML = `
        <div class="card border rounded-4 p-5 text-center bg-white shadow-sm my-3">
          <i class="fa-solid fa-boxes-packing text-muted fs-1 mb-3"></i>
          <h5 class="fw-bold text-dark mb-2">No Matching Pharmacies Found</h5>
          <p class="text-muted small mb-0">None of the nearby active pharmacies have all confirmed prescription items in stock.</p>
        </div>
      `;
    } else {
      list.innerHTML = data.pharmacies.map((p, idx) => {
        const fullBadge = p.full_fulfillment
          ? `<span class="badge bg-success text-white rounded-pill px-3 py-1.5 small fw-bold"><i class="fa-solid fa-circle-check me-1"></i> ${p.fulfillment_ratio} Full Match</span>`
          : `<span class="badge bg-warning-subtle text-warning-emphasis border border-warning-subtle rounded-pill px-3 py-1.5 small fw-semibold"><i class="fa-solid fa-boxes-stacked me-1"></i> ${p.fulfillment_ratio} Partial Availability</span>`;

        return `
          <div class="card border rounded-4 p-4 shadow-sm bg-white mb-3 hover-card transition-all" data-lat="${p.latitude}" data-lng="${p.longitude}">
            <div class="d-flex justify-content-between align-items-start mb-2">
              <div>
                <div class="d-flex align-items-center gap-2 mb-1.5">
                  ${fullBadge}
                  <span class="badge ${p.is_open_now ? 'bg-success-subtle text-success' : 'bg-secondary-subtle text-secondary'} rounded-pill px-2.5 py-1 small fw-semibold">
                    <i class="fa-solid fa-circle me-1" style="font-size: 0.45rem;"></i> ${p.is_open_now ? 'Open Now' : 'Closed'}
                  </span>
                  ${p.verified ? '<span class="badge bg-primary-subtle text-primary rounded-pill px-2 py-0.5 small"><i class="fa-solid fa-shield-check me-1"></i>Verified</span>' : ''}
                </div>
                <h5 class="fw-bold text-dark mb-1">
                  <a href="/pharmacy/${p.id}/" class="text-dark text-decoration-none">${p.name}</a>
                </h5>
                <p class="text-muted small mb-2">
                  <i class="fa-solid fa-location-dot text-primary me-1"></i> ${p.address}, ${p.city} &bull; <strong>${p.distance_km} km away</strong>
                </p>

                <!-- List of Available Items -->
                <div class="p-2.5 bg-light rounded-3 border">
                  <small class="fw-bold text-dark text-uppercase d-block mb-1" style="font-size: 0.68rem; letter-spacing: 0.5px;">Available Stock:</small>
                  <div class="d-flex flex-wrap gap-1.5">
                    ${(p.available_medicines || []).map(m => `
                      <span class="badge bg-white text-dark border rounded-pill px-2.5 py-1 small fw-semibold">
                        ${m.medicine_name} — ${m.price_formatted} (${m.stock} in stock)
                      </span>
                    `).join('')}
                  </div>
                </div>
              </div>

              <div class="text-end">
                <div class="fw-extrabold text-dark fs-4">${p.total_price_formatted}</div>
                <small class="text-muted d-block">Prescription Total</small>
                <div class="d-flex gap-2 mt-3 justify-content-end">
                  <a href="/pharmacy/${p.id}/" class="btn btn-sm btn-primary rounded-pill px-3 fw-semibold">
                    View Pharmacy
                  </a>
                  <a href="https://www.google.com/maps/dir/?api=1&destination=${p.latitude},${p.longitude}" target="_blank" rel="noopener noreferrer" class="btn btn-sm btn-light border rounded-circle d-flex align-items-center justify-content-center text-success" style="width: 32px; height: 32px;" title="Directions">
                    <i class="fa-solid fa-diamond-turn-right"></i>
                  </a>
                </div>
              </div>
            </div>
          </div>
        `;
      }).join('');
    }

    // Sync with Leaflet Map Pins
    if (typeof window.updatePharmacyMarkers === 'function') {
      window.updatePharmacyMarkers(data.pharmacies || []);
    }
  }

})();
