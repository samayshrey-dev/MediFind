/**
 * Medifind AI — Natural-Language Medicine Search Client Engine
 * Pipeline: User Query -> POST /api/ai/search/ -> Grounded Explanation -> Ranked Cards -> Leaflet Sync
 */
(function () {
  'use strict';

  let userCoords = null;

  // Request browser geolocation once on load
  if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        userCoords = {
          lat: pos.coords.latitude,
          lng: pos.coords.longitude
        };
      },
      () => {
        // Default to Chennai Central coordinates
        userCoords = { lat: 13.0827, lng: 80.2707 };
      },
      { timeout: 5000 }
    );
  }

  // Voice Search / Speech Recognition
  function setupSpeechRecognition(btnId, inputId, formId) {
    const micBtn = document.getElementById(btnId);
    const input = document.getElementById(inputId);
    const form = document.getElementById(formId);

    if (!micBtn || !input) return;

    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRec) {
      micBtn.style.display = 'none';
      return;
    }

    const recognition = new SpeechRec();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = 'en-IN';

    let isRecording = false;

    micBtn.addEventListener('click', (e) => {
      e.preventDefault();
      if (!isRecording) {
        try {
          recognition.start();
          isRecording = true;
          micBtn.classList.add('btn-danger', 'pulse-mic');
          micBtn.classList.remove('btn-light', 'text-muted');
          micBtn.innerHTML = '<i class="fa-solid fa-microphone-slash"></i>';
        } catch (err) {
          console.warn('Speech recognition error:', err);
        }
      } else {
        recognition.stop();
        isRecording = false;
        micBtn.classList.remove('btn-danger', 'pulse-mic');
        micBtn.classList.add('btn-light', 'text-muted');
        micBtn.innerHTML = '<i class="fa-solid fa-microphone"></i>';
      }
    });

    recognition.onresult = (event) => {
      const transcript = event.results[0][0].transcript;
      input.value = transcript;
      micBtn.classList.remove('btn-danger', 'pulse-mic');
      micBtn.classList.add('btn-light', 'text-muted');
      micBtn.innerHTML = '<i class="fa-solid fa-microphone"></i>';
      isRecording = false;

      if (form) {
        if (typeof window.executeAISearch === 'function') {
          window.executeAISearch(transcript);
        } else {
          form.submit();
        }
      }
    };

    recognition.onerror = () => {
      micBtn.classList.remove('btn-danger', 'pulse-mic');
      micBtn.classList.add('btn-light', 'text-muted');
      micBtn.innerHTML = '<i class="fa-solid fa-microphone"></i>';
      isRecording = false;
    };

    recognition.onend = () => {
      micBtn.classList.remove('btn-danger', 'pulse-mic');
      micBtn.classList.add('btn-light', 'text-muted');
      micBtn.innerHTML = '<i class="fa-solid fa-microphone"></i>';
      isRecording = false;
    };
  }

  // Core API caller
  async function performAISearch(query, radius = 5) {
    const payload = {
      query: query.trim(),
      latitude: userCoords ? userCoords.lat : 13.0827,
      longitude: userCoords ? userCoords.lng : 80.2707,
      radius_km: radius
    };

    const res = await fetch('/api/ai/search/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      throw new Error(`Server returned HTTP ${res.status}`);
    }

    return await res.json();
  }

  // Render AI Results into search page DOM
  function renderSearchResults(data) {
    const aiResponseCard = document.getElementById('aiResponseCard');
    const aiResponseText = document.getElementById('aiResponseText');
    const aiInterpretation = document.getElementById('aiInterpretationBadge');
    const emergencyBanner = document.getElementById('aiEmergencyBanner');
    const resultsContainer = document.getElementById('searchResultsList');
    const resultCountHeading = document.getElementById('resultCountHeading');

    // 1. Emergency Notice
    if (data.is_emergency && emergencyBanner) {
      emergencyBanner.classList.remove('d-none');
      emergencyBanner.innerHTML = `
        <div class="alert alert-danger border-0 shadow-sm rounded-4 p-3.5 d-flex align-items-start gap-3 mb-4">
          <i class="fa-solid fa-triangle-exclamation text-danger fs-3 mt-1"></i>
          <div>
            <h6 class="fw-bold text-danger mb-1">Immediate Medical Attention Recommended</h6>
            <p class="mb-2 text-dark small">${data.ai_response || 'Symptoms described indicate a potential acute medical emergency.'}</p>
            <div class="d-flex flex-wrap gap-2">
              <a href="tel:112" class="btn btn-sm btn-danger rounded-pill px-3 fw-bold">
                <i class="fa-solid fa-phone me-1"></i> Call Emergency (112)
              </a>
              <a href="https://www.google.com/maps/search/nearest+hospital+emergency+room" target="_blank" rel="noopener noreferrer" class="btn btn-sm btn-outline-danger rounded-pill px-3 fw-semibold">
                <i class="fa-solid fa-hospital me-1"></i> Locate Nearest Hospital ER
              </a>
            </div>
          </div>
        </div>
      `;
      if (aiResponseCard) aiResponseCard.classList.add('d-none');
      if (resultsContainer) resultsContainer.innerHTML = '';
      return;
    } else if (emergencyBanner) {
      emergencyBanner.classList.add('d-none');
    }

    // 2. AI Grounded Explanation & Ambiguity Clarification Card
    if (aiResponseCard && aiResponseText) {
      aiResponseCard.classList.remove('d-none');
      
      let ambiguityHtml = '';
      if (data.requires_clarification && data.candidate_matches && data.candidate_matches.length > 0) {
        const buttons = data.candidate_matches.map(m => `
          <button type="button" class="btn btn-sm btn-outline-primary rounded-pill px-3 py-1.5 fw-bold search-clarification-btn" data-query="${m.name} ${m.dosage || ''}">
            <i class="fa-solid fa-capsules me-1"></i> ${m.name} ${m.dosage ? '(' + m.dosage + ')' : ''}
          </button>
        `).join('');

        ambiguityHtml = `
          <div class="alert alert-warning border-0 rounded-4 p-3 mb-3 shadow-inner">
            <h6 class="fw-bold text-dark mb-1"><i class="fa-solid fa-circle-question text-warning me-1.5"></i> ${data.clarification_message || 'Multiple matching items found. Select the specific medicine:'}</h6>
            <div class="d-flex flex-wrap gap-2 mt-2.5">
              ${buttons}
            </div>
          </div>
        `;
      }

      aiResponseText.innerHTML = ambiguityHtml + (data.ai_response || '').replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
      if (aiInterpretation && data.interpretation) {
        aiInterpretation.innerText = data.interpretation;
        aiInterpretation.classList.remove('d-none');
      }

      // Attach listener to clarification buttons
      document.querySelectorAll('.search-clarification-btn').forEach(btn => {
        btn.addEventListener('click', () => {
          const newQ = btn.getAttribute('data-query');
          const mainInput = document.getElementById('searchQueryInput') || document.getElementById('navbarSearchInput');
          if (mainInput) mainInput.value = newQ;
          if (typeof window.executeAISearch === 'function') {
            window.executeAISearch(newQ);
          }
        });
      });
    }

    // 3. Update Result Count Heading
    if (resultCountHeading) {
      resultCountHeading.innerText = `${data.total_results || 0} Pharmacies with ${data.query}`;
    }

    // 4. Render Pharmacy Cards
    if (resultsContainer) {
      if (!data.pharmacies || data.pharmacies.length === 0) {
        resultsContainer.innerHTML = `
          <div class="card border rounded-4 p-5 text-center bg-white shadow-sm my-4">
            <div class="rounded-circle bg-light d-inline-flex align-items-center justify-content-center mx-auto mb-3" style="width: 64px; height: 64px;">
              <i class="fa-solid fa-pills text-muted fs-3"></i>
            </div>
            <h5 class="fw-bold text-dark mb-2">No Matching Stock Found in Selected Radius</h5>
            <p class="text-muted small mb-4" style="max-width: 480px; margin: 0 auto;">
              We couldn't locate active inventory for "${data.query}" within ${data.radius_km || 5} km. Try expanding your search radius or setting a restock alert.
            </p>
            <div class="d-flex justify-content-center flex-wrap gap-2">
              <button class="btn btn-primary rounded-pill px-4 fw-semibold" onclick="window.expandSearchRadius()">
                <i class="fa-solid fa-arrows-up-down-left-right me-1.5"></i> Expand Radius (15 km)
              </button>
              <a href="/search/" class="btn btn-outline-secondary rounded-pill px-4 fw-semibold">
                Browse Full Catalog
              </a>
            </div>
          </div>
        `;
      } else {
        resultsContainer.innerHTML = data.pharmacies.map((p, idx) => `
          <div class="card border rounded-4 p-4 shadow-sm bg-white mb-3 hover-card transition-all" data-pharmacy-id="${p.id}" data-lat="${p.latitude}" data-lng="${p.longitude}">
            <div class="d-flex justify-content-between align-items-start mb-2">
              <div>
                <div class="d-flex align-items-center gap-2 mb-1">
                  <span class="badge ${p.is_open_now ? 'bg-success-subtle text-success border border-success-subtle' : 'bg-secondary-subtle text-secondary'} rounded-pill px-2.5 py-1 small fw-bold">
                    <i class="fa-solid fa-circle ${p.is_open_now ? 'text-success' : 'text-secondary'} me-1" style="font-size: 0.45rem; vertical-align: middle;"></i> ${p.is_open_now ? 'Open Now' : 'Closed'}
                  </span>
                  ${p.verified ? '<span class="badge bg-primary-subtle text-primary border border-primary-subtle rounded-pill px-2 py-0.5 small"><i class="fa-solid fa-circle-check me-1"></i>Verified</span>' : ''}
                  ${idx === 0 ? '<span class="badge bg-warning-subtle text-warning-emphasis border border-warning-subtle rounded-pill px-2 py-0.5 small fw-bold"><i class="fa-solid fa-star me-1"></i>Best Match</span>' : ''}
                </div>
                <h5 class="fw-bold text-dark mb-1">
                  <a href="/pharmacy/${p.id}/" class="text-dark text-decoration-none">${p.name}</a>
                </h5>
                <p class="text-muted small mb-1">
                  <i class="fa-solid fa-location-dot text-primary me-1"></i> ${p.address}, ${p.city}
                </p>
                <div class="d-flex align-items-center gap-3 text-muted small mt-2">
                  <span><i class="fa-solid fa-road me-1 text-muted"></i><strong>${p.distance_km} km</strong> away</span>
                  <span><i class="fa-solid fa-boxes-stacked me-1 text-muted"></i><strong class="text-success">${p.stock_quantity}</strong> units available</span>
                  ${p.prescription_required ? '<span class="text-warning-emphasis fw-semibold"><i class="fa-solid fa-file-prescription me-1"></i>Rx Required</span>' : ''}
                </div>
              </div>
              <div class="text-end">
                <div class="fw-extrabold text-dark fs-4">${p.price_formatted}</div>
                <small class="text-muted d-block">Retail Price</small>
                <div class="d-flex gap-2 mt-3 justify-content-end">
                  <a href="/reserve/${p.inventory_id}/" class="btn btn-sm btn-primary rounded-pill px-3 fw-semibold">
                    Reserve
                  </a>
                  <a href="https://www.google.com/maps/dir/?api=1&destination=${p.latitude},${p.longitude}" target="_blank" rel="noopener noreferrer" class="btn btn-sm btn-light border rounded-circle d-flex align-items-center justify-content-center text-success" style="width: 32px; height: 32px;" title="Directions">
                    <i class="fa-solid fa-diamond-turn-right"></i>
                  </a>
                </div>
              </div>
            </div>
          </div>
        `).join('');
      }
    }

    // 5. Update Leaflet Map
    if (typeof window.updatePharmacyMarkers === 'function') {
      window.updatePharmacyMarkers(data.pharmacies || []);
    }
  }

  // Global trigger function
  window.executeAISearch = async function (query, radius = 5) {
    if (!query) return;

    const input = document.getElementById('aiSearchInput');
    if (input) input.value = query;

    const btn = document.getElementById('aiSearchSubmitBtn');
    const originalBtnHtml = btn ? btn.innerHTML : '';
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i>';
    }

    try {
      const data = await performAISearch(query, radius);
      renderSearchResults(data);
    } catch (err) {
      console.error('AI search failed:', err);
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = originalBtnHtml;
      }
    }
  };

  window.expandSearchRadius = function () {
    const input = document.getElementById('aiSearchInput');
    const query = input ? input.value : 'medicine';
    window.executeAISearch(query, 15);
  };

  // Init on DOM load
  document.addEventListener('DOMContentLoaded', () => {
    setupSpeechRecognition('heroVoiceMicBtn', 'heroSearchInput', 'heroSearchForm');
    setupSpeechRecognition('aiVoiceMicBtn', 'aiSearchInput', 'aiSearchForm');

    const aiForm = document.getElementById('aiSearchForm');
    if (aiForm) {
      aiForm.addEventListener('submit', (e) => {
        const input = document.getElementById('aiSearchInput');
        if (input && input.value.trim()) {
          // If on search page, execute in-place
          if (document.getElementById('searchResultsList')) {
            e.preventDefault();
            window.executeAISearch(input.value.trim());
          }
        }
      });
    }
  });

})();
