/**
 * MedFinder Agentic Commerce — Production Controller
 * Coordinates with /api/ai/agent/search/, /api/commerce/snapshot/,
 * and /api/payments/ (Razorpay Test Mode Integration)
 */

(function () {
  'use strict';

  let currentSessionId = null;
  let activeOrderSnapshot = null;
  let userCoordinates = { lat: null, lng: null };

  // Detect GPS Coordinates silently
  function initGeolocation() {
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        function (pos) {
          userCoordinates.lat = pos.coords.latitude;
          userCoordinates.lng = pos.coords.longitude;
          const latInput = document.getElementById('userLat');
          const lngInput = document.getElementById('userLng');
          if (latInput) latInput.value = userCoordinates.lat;
          if (lngInput) lngInput.value = userCoordinates.lng;
        },
        function () {},
        { timeout: 6000, maximumAge: 60000 }
      );
    }
  }

  // Execute Search Discovery
  async function runCommerceSearch(query) {
    if (!query || !query.trim()) return;

    const resultsContainer = document.getElementById('agentResultsArea');
    const staticResultsArea = document.getElementById('staticResultsArea');
    if (!resultsContainer) return;

    if (staticResultsArea) {
      staticResultsArea.style.display = 'none';
    }

    resultsContainer.classList.remove('d-none');
    resultsContainer.innerHTML = `
      <div class="card border rounded-4 p-4 shadow-sm my-3 bg-white">
        <div class="d-flex align-items-center mb-3">
          <div class="spinner-border spinner-border-sm text-primary me-2" role="status"></div>
          <span class="fw-semibold text-dark">Finding verified pharmacies, nearest store, and lowest price...</span>
        </div>
        <div class="skeleton-box mb-2" style="height: 24px; width: 60%;"></div>
        <div class="skeleton-box mb-2" style="height: 16px; width: 40%;"></div>
        <div class="skeleton-box" style="height: 80px; width: 100%;"></div>
      </div>
    `;

    try {
      const response = await fetch('/api/ai/agent/search/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCsrfToken()
        },
        body: JSON.stringify({
          query: query,
          lat: userCoordinates.lat,
          lng: userCoordinates.lng,
          session_id: currentSessionId
        })
      });

      const data = await response.json();
      currentSessionId = data.session_id;

      renderCommerceResults(data);

      // Sync map markers if MedFinderMap is loaded
      if (window.MedFinderMap && typeof window.MedFinderMap.updateMarkers === 'function') {
        const markers = data.all_options && data.all_options.length > 0
          ? data.all_options
          : (data.best_match ? [data.best_match] : []);
        window.MedFinderMap.updateMarkers(markers);
      }

    } catch (err) {
      console.error('Search error:', err);
      resultsContainer.innerHTML = `
        <div class="alert alert-danger rounded-4 p-3 border-0 my-3">
          <h6 class="fw-bold mb-1">Something went wrong</h6>
          <p class="mb-0 small text-muted">We couldn't load pharmacy availability. Please try again.</p>
        </div>
      `;
    }
  }

  // Render Clean Commerce Results with Nearest, Cheapest & Complete Inventory
  function renderCommerceResults(data) {
    const resultsContainer = document.getElementById('agentResultsArea');
    if (!resultsContainer) return;

    let html = '';

    // 1. Structured Search Context (Clean metadata chips)
    const intent = data.intent || {};
    const hasCorrection = intent.matched_medicine_name &&
      intent.medicine_query &&
      intent.matched_medicine_name.toLowerCase() !== intent.medicine_query.toLowerCase();

    if (hasCorrection) {
      html += `
        <div class="alert alert-info border-0 rounded-4 py-2 px-3 mb-3 d-flex align-items-center justify-content-between shadow-sm">
          <div>
            <i class="fa-solid fa-circle-info text-primary me-2"></i>
            <span class="text-dark">Showing results for <strong>${escapeHtml(intent.matched_medicine_name)}</strong></span>
            <small class="text-muted ms-1">(searched for "${escapeHtml(intent.medicine_query)}")</small>
          </div>
        </div>
      `;
    }

    if (intent.medicine_query || intent.max_distance_km) {
      html += `
        <div class="search-intent-bar shadow-sm mb-3">
          <span class="text-muted small fw-semibold me-1">Filters:</span>
          ${intent.matched_medicine_name ? `<span class="intent-pill"><i class="fa-solid fa-pills text-primary"></i> ${escapeHtml(intent.matched_medicine_name)}</span>` : (intent.medicine_query ? `<span class="intent-pill"><i class="fa-solid fa-pills text-primary"></i> ${escapeHtml(intent.medicine_query)}</span>` : '')}
          ${intent.strength_raw ? `<span class="intent-pill text-muted">${escapeHtml(intent.strength_raw)}</span>` : ''}
          ${intent.dosage_form ? `<span class="intent-pill text-muted">${escapeHtml(intent.dosage_form)}</span>` : ''}
          ${intent.max_distance_km ? `<span class="intent-pill text-secondary"><i class="fa-solid fa-location-dot me-1"></i> Within ${escapeHtml(intent.max_distance_km)} km</span>` : ''}
          <span class="intent-pill bg-light text-dark fw-bold">${escapeHtml(formatGoal(intent.optimization_goal))}</span>
        </div>
      `;
    }


    // 2. Medical Safety Warning
    if (data.medical_safety_warning) {
      html += `
        <div class="alert alert-warning rounded-4 p-3 border-0 mb-3 shadow-sm d-flex align-items-start gap-2">
          <i class="fa-solid fa-triangle-exclamation text-warning fs-5 mt-1"></i>
          <div>
            <div class="fw-bold text-dark mb-1">Medical Notice</div>
            <p class="mb-0 small text-dark">${escapeHtml(data.medical_safety_warning)}</p>
          </div>
        </div>
      `;
    }

    // 3. Ambiguous Query Clarification
    if (data.needs_clarification) {
      html += `
        <div class="card border rounded-4 p-4 mb-3 shadow-sm bg-white">
          <h5 class="fw-bold text-dark mb-2">${escapeHtml(data.clarification_message || 'Which medicine do you need?')}</h5>
          <div class="d-flex flex-wrap gap-2 mt-3">
            ${(data.intent?.suggested_options || []).map(opt => `
              <button class="btn btn-outline-primary btn-sm rounded-pill agent-suggestion-btn" data-query="${escapeHtml(opt)}">
                ${escapeHtml(opt)}
              </button>
            `).join('')}
          </div>
        </div>
      `;
    }

    // 4. Best Match & Side-by-Side Highlights (Cheapest & Nearest)
    if (data.best_match) {
      const bm = data.best_match;
      const cheapest = data.cheapest_option;
      const nearest = data.nearest_option;

      html += `
        <!-- Best Match Banner -->
        <div class="recommended-card mb-4">
          <div class="recommended-badge">
            <i class="fa-solid fa-check me-1"></i> Best Match
          </div>

          <div class="row align-items-center g-4">
            <div class="col-lg-8">
              <div class="d-flex align-items-center gap-2 mb-2">
                <span class="badge ${bm.is_open ? 'bg-success' : 'bg-secondary'} rounded-pill px-2 py-1">
                  ● ${bm.is_open ? 'Open Now' : 'Closed'}
                </span>
                <span class="badge bg-light text-dark border rounded-pill px-2 py-1">
                  ${bm.stock} in stock
                </span>
                ${bm.prescription_required ? `
                  <span class="badge bg-danger-subtle text-danger rounded-pill px-2 py-1">
                    Prescription Required
                  </span>
                ` : ''}
              </div>

              <h3 class="fw-bold text-dark mb-1">${escapeHtml(bm.medicine_name)}</h3>
              <div class="text-muted mb-2">
                <strong class="text-dark">${escapeHtml(bm.pharmacy_name)}</strong> &bull; ${escapeHtml(bm.pharmacy_address)}, ${escapeHtml(bm.pharmacy_city)}
              </div>

              ${bm.distance_km !== null ? `
                <div class="text-secondary small mb-3">
                  <i class="fa-solid fa-route text-muted me-1"></i> ${bm.distance_km} km away &bull; Verified Partner Store
                </div>
              ` : ''}

              <!-- Explainable Reasoning Callout -->
              <div class="reasoning-callout">
                <div class="fw-bold text-dark small mb-1">Why this option?</div>
                <div>${escapeHtml(data.explanation || 'Lowest verified price among available pharmacies within your selected area.')}</div>
              </div>
            </div>

            <div class="col-lg-4 text-lg-end border-start-lg ps-lg-4">
              <div class="text-muted small fw-semibold">Unit Price</div>
              <div class="recommended-price mb-3">₹${parseFloat(bm.price).toFixed(2)}</div>

              <!-- Order Review & Checkout Button -->
              <div class="order-review-box" id="approvalGateContainer">
                <a href="/reserve/${bm.inventory_id}/" class="btn btn-primary w-100 py-2.5 fw-bold text-decoration-none d-flex align-items-center justify-content-center gap-2 mb-2 rounded-pill shadow-sm">
                  <span>Review Purchase &rarr;</span>
                </a>
                <div class="d-flex justify-content-center align-items-center gap-2 text-muted small">
                  <span class="badge bg-light text-dark border rounded-pill px-2 py-1"><i class="fa-solid fa-store text-primary me-1"></i> Pay on Pickup</span>
                  <span class="text-muted">&bull;</span>
                  <span class="badge bg-light text-dark border rounded-pill px-2 py-1"><i class="fa-solid fa-credit-card text-success me-1"></i> Razorpay Test</span>
                </div>
              </div>

              <div class="mt-2">
                <a href="/pharmacy/${bm.pharmacy_id}/" class="btn btn-link btn-sm text-decoration-none text-muted">
                  View Pharmacy Profile &rarr;
                </a>
              </div>
            </div>
          </div>
        </div>

        <!-- Quick Comparison: Cheapest vs Nearest Highlights -->
        <div class="row g-3 mb-4">
          ${cheapest ? `
            <div class="col-md-6">
              <div class="card border rounded-4 p-3 shadow-sm bg-white h-100" style="border-left: 4px solid #10b981 !important;">
                <div class="d-flex justify-content-between align-items-center mb-1">
                  <span class="badge bg-success-subtle text-success rounded-pill px-2.5 py-1 small fw-bold">
                    <i class="fa-solid fa-tag me-1"></i> Lowest Price Option
                  </span>
                  <span class="fs-5 fw-extrabold text-success">₹${parseFloat(cheapest.price).toFixed(2)}</span>
                </div>
                <h6 class="fw-bold text-dark mb-0 mt-2">${escapeHtml(cheapest.pharmacy_name)}</h6>
                <div class="text-muted small mb-3">
                  ${cheapest.distance_km !== null ? `<i class="fa-solid fa-location-dot text-muted me-1"></i> ${cheapest.distance_km} km away &bull; ` : ''}${cheapest.stock} in stock
                </div>
                <div class="mt-auto d-flex justify-content-between align-items-center">
                  <a href="/pharmacy/${cheapest.pharmacy_id}/" class="text-muted small text-decoration-none">View store</a>
                  <a href="/reserve/${cheapest.inventory_id}/" class="btn btn-sm btn-outline-success rounded-pill px-3 fw-semibold text-decoration-none">
                    Review purchase &rarr;
                  </a>
                </div>
              </div>
            </div>
          ` : ''}

          ${nearest ? `
            <div class="col-md-6">
              <div class="card border rounded-4 p-3 shadow-sm bg-white h-100" style="border-left: 4px solid #0284c7 !important;">
                <div class="d-flex justify-content-between align-items-center mb-1">
                  <span class="badge bg-primary-subtle text-primary rounded-pill px-2.5 py-1 small fw-bold">
                    <i class="fa-solid fa-location-crosshairs me-1"></i> Nearest Pharmacy
                  </span>
                  <span class="fs-5 fw-extrabold text-primary">${nearest.distance_km !== null ? `${nearest.distance_km} km` : 'Near you'}</span>
                </div>
                <h6 class="fw-bold text-dark mb-0 mt-2">${escapeHtml(nearest.pharmacy_name)}</h6>
                <div class="text-muted small mb-3">
                  ₹${parseFloat(nearest.price).toFixed(2)} &bull; ${nearest.stock} in stock &bull; ${nearest.is_open ? 'Open now' : 'Closed'}
                </div>
                <div class="mt-auto d-flex justify-content-between align-items-center">
                  <a href="/pharmacy/${nearest.pharmacy_id}/" class="text-muted small text-decoration-none">View store</a>
                  <a href="/reserve/${nearest.inventory_id}/" class="btn btn-sm btn-outline-primary rounded-pill px-3 fw-semibold text-decoration-none">
                    Review purchase &rarr;
                  </a>
                </div>
              </div>
            </div>
          ` : ''}
        </div>
      `;
    } else if (!data.needs_clarification && !data.medical_safety_warning) {
      html += `
        <div class="card border rounded-4 p-5 text-center my-4 shadow-sm bg-white">
          <i class="fa-solid fa-box-open fs-2 text-muted mb-3"></i>
          <h5 class="fw-bold text-dark mb-1">No medicines found nearby</h5>
          <p class="text-muted small mb-0">${escapeHtml(data.explanation || 'We could not find matching stock at nearby pharmacies. Try searching with a broader name or increasing your search radius.')}</p>
        </div>
      `;
    }

    // 5. Complete List of All Available Matching Results
    if (data.all_options && data.all_options.length > 0) {
      html += `
        <div class="mt-4 mb-4">
          <div class="d-flex justify-content-between align-items-center mb-3">
            <h5 class="fw-bold text-dark mb-0">
              All Available Results (${data.all_options.length} Verified Stores)
            </h5>
            <span class="badge bg-light text-muted border rounded-pill px-2 py-1 small">Real-time Stock</span>
          </div>

          <div class="d-flex flex-column gap-3">
            ${data.all_options.map((opt, idx) => `
              <div class="card border rounded-4 p-3 shadow-sm bg-white hover-elevate" style="transition: all 0.2s ease;">
                <div class="d-flex justify-content-between align-items-start mb-2">
                  <div>
                    <div class="d-flex align-items-center gap-2 mb-1">
                      <span class="badge ${opt.is_open ? 'bg-success' : 'bg-secondary'} rounded-pill px-2 py-1" style="font-size: 0.72rem;">
                        ● ${opt.is_open ? 'Open' : 'Closed'}
                      </span>
                      <span class="text-muted small">${opt.stock > 0 ? `${opt.stock} available` : 'Out of stock'}</span>
                      ${opt.distance_km !== null ? `
                        <span class="badge bg-light text-secondary border rounded-pill px-2 py-1" style="font-size: 0.72rem;">
                          <i class="fa-solid fa-location-dot me-1"></i> ${opt.distance_km} km
                        </span>
                      ` : ''}
                    </div>
                    <h6 class="fw-bold text-dark mb-0">${escapeHtml(opt.medicine_name)}</h6>
                    <small class="text-muted">${escapeHtml(opt.pharmacy_name)} &bull; ${escapeHtml(opt.pharmacy_address || '')} ${escapeHtml(opt.pharmacy_city || '')}</small>
                  </div>
                  <div class="text-end">
                    <div class="fs-5 fw-extrabold text-dark">₹${parseFloat(opt.price).toFixed(2)}</div>
                  </div>
                </div>

                <div class="pt-2 border-top mt-2 d-flex justify-content-between align-items-center flex-wrap gap-2">
                  <div class="small text-muted">
                    <i class="fa-solid fa-clock text-muted me-1"></i> Closes at ${escapeHtml(opt.closing_time || '22:00')}
                  </div>
                  <div class="d-flex gap-2">
                    <a href="/pharmacy/${opt.pharmacy_id}/" class="btn btn-sm btn-outline-secondary rounded-pill px-3">
                      Store Info
                    </a>
                    ${opt.stock > 0 ? `
                      <button type="button" class="btn btn-sm btn-primary rounded-pill px-3 fw-semibold btn-select-pharmacy" data-inventory-id="${opt.inventory_id}">
                        Review &amp; Pay
                      </button>
                    ` : `
                      <button class="btn btn-sm btn-light text-muted rounded-pill px-3" disabled>Out of stock</button>
                    `}
                  </div>
                </div>
              </div>
            `).join('')}
          </div>
        </div>
      `;
    }

    // 6. Developer / Activity Log Details (Collapsible)
    if (data.audit_trail && data.audit_trail.length > 0) {
      html += `
        <div class="mt-4 text-end">
          <button class="btn btn-sm btn-link text-muted text-decoration-none" type="button" data-bs-toggle="collapse" data-bs-target="#auditTrailCollapse">
            <small><i class="fa-solid fa-list-check me-1"></i> Activity details (${data.audit_trail.length} events)</small>
          </button>
          <div class="collapse mt-2 text-start" id="auditTrailCollapse">
            <div class="audit-drawer shadow">
              <div class="d-flex justify-content-between border-bottom pb-1 mb-2 text-light">
                <small class="fw-bold">Decision Trail</small>
                <small class="text-muted">ID: ${escapeHtml(data.session_id || '')}</small>
              </div>
              ${data.audit_trail.map(ev => `
                <div class="mb-1">
                  <span class="badge bg-secondary text-white">${escapeHtml(ev.event_type)}</span>
                  <pre class="mb-0 text-muted" style="font-size:0.7rem;">${escapeHtml(JSON.stringify(ev.payload))}</pre>
                </div>
              `).join('')}
            </div>
          </div>
        </div>
      `;
    }

    resultsContainer.innerHTML = html;
    if (window.MedFinderMotion && typeof window.MedFinderMotion.refreshReveals === 'function') {
      window.MedFinderMotion.refreshReveals();
    }
    attachResultEvents();
  }

  // STEP 1: Review Purchase Snapshot (Server-Side Snapshot Creation)
  async function reviewPurchaseSnapshot(inventoryId) {
    const container = document.getElementById('approvalGateContainer');
    if (!container) return;

    container.innerHTML = `
      <div class="text-center py-2 w-100">
        <div class="spinner-border spinner-border-sm text-primary me-2"></div>
        <span class="small fw-semibold text-dark">Locking verified price &amp; stock...</span>
      </div>
    `;

    try {
      const response = await fetch('/api/commerce/snapshot/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCsrfToken()
        },
        body: JSON.stringify({
          session_id: currentSessionId,
          inventory_id: parseInt(inventoryId),
          quantity: 1
        })
      });

      const data = await response.json();
      if (!data.success) {
        container.innerHTML = `
          <div class="alert alert-danger small mb-0 w-100">
            ${escapeHtml(data.message || 'Could not verify medicine availability.')}
          </div>
        `;
        return;
      }

      activeOrderSnapshot = data;

      // Render Approved Transaction Card
      container.innerHTML = `
        <div class="card border-primary border-2 rounded-4 p-3 bg-light shadow-sm text-start w-100 mb-2">
          <div class="d-flex justify-content-between align-items-center mb-2 pb-2 border-bottom">
            <span class="badge bg-emerald text-white fw-bold px-2 py-1"><i class="fa-solid fa-check me-1"></i> APPROVED TRANSACTION</span>
            <small class="font-monospace text-muted">${escapeHtml(data.order_reference)}</small>
          </div>
          <div class="small text-dark mb-1"><strong>Medicine:</strong> ${escapeHtml(data.medicine_name)}</div>
          <div class="small text-dark mb-1"><strong>Pharmacy:</strong> ${escapeHtml(data.pharmacy_name)}</div>
          <div class="small text-dark mb-2"><strong>Total Payable:</strong> <span class="fw-bold text-emerald fs-6">₹${data.total_amount.toFixed(2)}</span> (${data.quantity} unit)</div>
          
          <button type="button" class="btn btn-success w-100 fw-bold py-2 rounded-pill shadow-sm" id="btnConfirmAndPay" data-order-ref="${escapeHtml(data.order_reference)}">
            <i class="fa-solid fa-lock me-1"></i> Confirm &amp; Pay ₹${data.total_amount.toFixed(2)}
          </button>
        </div>
      `;

      const confirmBtn = document.getElementById('btnConfirmAndPay');
      if (confirmBtn) {
        confirmBtn.addEventListener('click', function () {
          initiateRazorpayPayment(data.order_reference);
        });
      }

    } catch (err) {
      console.error('Snapshot Error:', err);
      container.innerHTML = `
        <div class="alert alert-danger small mb-0 w-100">
          Server connection error. Please try again.
        </div>
      `;
    }
  }

  // STEP 2: Initiate Razorpay Test Mode Payment
  async function initiateRazorpayPayment(orderReference) {
    const container = document.getElementById('approvalGateContainer');
    if (container) {
      container.innerHTML = `
        <div class="text-center py-3 w-100">
          <div class="spinner-border spinner-border-sm text-success me-2"></div>
          <span class="small fw-bold text-dark">Connecting to Razorpay Test Gateway...</span>
        </div>
      `;
    }

    try {
      const response = await fetch('/api/payments/create-order/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCsrfToken()
        },
        body: JSON.stringify({
          order_reference: orderReference
        })
      });

      const data = await response.json();

      // Bounded Commerce Safety: Price or Stock Changed
      if (response.status === 409) {
        if (data.error_type === 'PRICE_CHANGED') {
          container.innerHTML = `
            <div class="card border-warning border-2 rounded-4 p-3 bg-warning-subtle text-start w-100">
              <h6 class="fw-bold text-dark mb-1"><i class="fa-solid fa-triangle-exclamation text-warning me-1"></i> Price Changed</h6>
              <p class="small text-dark mb-2">${escapeHtml(data.message)}</p>
              <div class="d-flex justify-content-between small mb-2">
                <span>Previous: ₹${data.old_price.toFixed(2)}</span>
                <span class="fw-bold text-emerald">New: ₹${data.new_price.toFixed(2)}</span>
              </div>
              <button class="btn btn-outline-dark btn-sm w-100 rounded-pill" onclick="window.MedFinderCommerce.search(document.getElementById('medicineSearch').value)">
                Re-evaluate Options
              </button>
            </div>
          `;
          return;
        } else if (data.error_type === 'OUT_OF_STOCK') {
          container.innerHTML = `
            <div class="alert alert-danger small rounded-4 p-3 text-start w-100">
              <h6 class="fw-bold mb-1">Item Out of Stock</h6>
              <p class="mb-0">${escapeHtml(data.message)}</p>
            </div>
          `;
          return;
        }
      }

      if (!data.success) {
        container.innerHTML = `
          <div class="alert alert-danger small rounded-4 p-3 text-start w-100">
            ${escapeHtml(data.message || 'Payment initialization failed.')}
          </div>
        `;
        return;
      }

      // Launch Razorpay Checkout Modal
      if (typeof Razorpay === 'undefined') {
        alert('Razorpay Checkout SDK is still loading. Please try again in a moment.');
        return;
      }

      const options = {
        key: data.key_id,
        amount: data.amount,
        currency: data.currency || 'INR',
        name: 'MedFinder Commerce',
        description: `${data.medicine_name} at ${data.pharmacy_name}`,
        order_id: data.razorpay_order_id,
        notes: {
          order_reference: data.order_reference
        },
        theme: {
          color: '#10b981'
        },
        handler: async function (rzpResponse) {
          // Server-side Payment Verification
          await verifyPaymentOnServer(
            data.order_reference,
            rzpResponse.razorpay_order_id,
            rzpResponse.razorpay_payment_id,
            rzpResponse.razorpay_signature
          );
        },
        modal: {
          ondismiss: async function () {
            // Record checkout abandonment / dismissal
            await fetch('/api/payments/fail/', {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
              },
              body: JSON.stringify({
                order_reference: data.order_reference,
                reason: 'Checkout window dismissed by user'
              })
            });
            renderPaymentFailureCard(container, data.order_reference, 'No payment was completed. Your order remains pending.');
          }
        }
      };

      const rzpInstance = new Razorpay(options);
      rzpInstance.open();

    } catch (err) {
      console.error('Payment Error:', err);
      if (container) {
        container.innerHTML = `
          <div class="alert alert-danger small mb-0 w-100">
            Payment system connection error. Please try again.
          </div>
        `;
      }
    }
  }

  // STEP 3: Server-side Payment Verification
  async function verifyPaymentOnServer(orderReference, rzpOrderId, rzpPaymentId, rzpSignature) {
    const container = document.getElementById('approvalGateContainer');
    if (container) {
      container.innerHTML = `
        <div class="text-center py-3 w-100">
          <div class="spinner-border spinner-border-sm text-success me-2"></div>
          <span class="small fw-bold text-dark">Verifying secure signature with Razorpay...</span>
        </div>
      `;
    }

    try {
      const response = await fetch('/api/payments/verify/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCsrfToken()
        },
        body: JSON.stringify({
          order_reference: orderReference,
          razorpay_order_id: rzpOrderId,
          razorpay_payment_id: rzpPaymentId,
          razorpay_signature: rzpSignature
        })
      });

      const data = await response.json();
      if (data.success) {
        // Redirect to full order confirmation receipt
        window.location.href = `/orders/confirmed/${orderReference}/`;
      } else {
        renderPaymentFailureCard(container, orderReference, data.message || 'Signature verification rejected by server.');
      }
    } catch (err) {
      console.error('Verification Error:', err);
      renderPaymentFailureCard(container, orderReference, 'Could not verify transaction with server.');
    }
  }

  // Render Graceful Payment Failure Card with Try Again button
  function renderPaymentFailureCard(container, orderReference, reason) {
    if (!container) return;
    container.innerHTML = `
      <div class="card border-danger border-2 rounded-4 p-3 bg-danger-subtle text-start w-100 shadow-sm">
        <div class="d-flex align-items-center mb-2">
          <i class="fa-solid fa-circle-xmark text-danger fs-5 me-2"></i>
          <span class="fw-bold text-danger">Payment unsuccessful</span>
        </div>
        <p class="small text-dark mb-2">No payment has been confirmed for order <strong>#${escapeHtml(orderReference)}</strong>.</p>
        <p class="text-muted" style="font-size: 0.78rem;">${escapeHtml(reason)}</p>
        <button type="button" class="btn btn-primary w-100 rounded-pill btn-sm fw-semibold" id="btnRetryPayment" data-order-ref="${escapeHtml(orderReference)}">
          <i class="fa-solid fa-arrow-rotate-right me-1"></i> Try again
        </button>
      </div>
    `;

    const retryBtn = document.getElementById('btnRetryPayment');
    if (retryBtn) {
      retryBtn.addEventListener('click', function () {
        initiateRazorpayPayment(orderReference);
      });
    }
  }

  // Attach Event Handlers
  function attachResultEvents() {
    const reviewBtn = document.getElementById('btnReviewPurchase');
    if (reviewBtn) {
      reviewBtn.addEventListener('click', function () {
        const invId = this.getAttribute('data-inventory-id');
        reviewPurchaseSnapshot(invId);
      });
    }

    document.querySelectorAll('.btn-select-pharmacy').forEach(btn => {
      btn.addEventListener('click', function () {
        const invId = this.getAttribute('data-inventory-id');
        reviewPurchaseSnapshot(invId);
        // Smooth scroll up to review card
        const gate = document.getElementById('approvalGateContainer');
        if (gate) gate.scrollIntoView({ behavior: 'smooth', block: 'center' });
      });
    });

    document.querySelectorAll('.agent-suggestion-btn').forEach(btn => {
      btn.addEventListener('click', function () {
        const q = this.getAttribute('data-query');
        const input = document.getElementById('medicineSearch');
        if (input) input.value = q;
        runCommerceSearch(q);
      });
    });
  }

  function formatGoal(goal) {
    if (goal === 'lowest_price') return 'Lowest Price';
    if (goal === 'closest') return 'Nearest Pharmacy';
    if (goal === 'fastest') return 'Fastest Option';
    return 'Best Match';
  }

  function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function getCsrfToken() {
    const cookieValue = document.cookie
      .split('; ')
      .find(row => row.startsWith('csrftoken='))
      ?.split('=')[1];
    return cookieValue || '';
  }

  // Initialization on DOM Ready
  document.addEventListener('DOMContentLoaded', function () {
    initGeolocation();

    // Bind Search Tag Chips
    document.querySelectorAll('.search-tag-chip').forEach(chip => {
      chip.addEventListener('click', function (e) {
        e.preventDefault();
        const queryText = this.getAttribute('data-query') || this.innerText.trim();
        const input = document.getElementById('medicineSearch');
        if (input) input.value = queryText;
        runCommerceSearch(queryText);
      });
    });

    // Bind Search Form
    const searchForm = document.getElementById('agentSearchForm') || document.getElementById('searchForm');
    if (searchForm) {
      searchForm.addEventListener('submit', function (e) {
        e.preventDefault();
        const input = document.getElementById('medicineSearch');
        if (input && input.value) {
          runCommerceSearch(input.value);
        }
      });
    }

    // Auto-run if query param exists
    const urlParams = new URLSearchParams(window.location.search);
    const medQuery = urlParams.get('medicine');
    if (medQuery && document.getElementById('agentResultsArea')) {
      const input = document.getElementById('medicineSearch');
      if (input) input.value = medQuery;
      runCommerceSearch(medQuery);
    }
  });

  window.MedFinderCommerce = {
    search: runCommerceSearch,
    review: reviewPurchaseSnapshot,
    pay: initiateRazorpayPayment
  };
})();
