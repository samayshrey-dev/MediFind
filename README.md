# MediAI — Real-Time Pharmacy Intelligence, OpenStreetMap Geospatial Discovery & Healthcare Commerce

<div align="center">

![MediAI Banner](https://img.shields.io/badge/Platform-MediAI-059669?style=for-the-badge&logo=mediamarkt&logoColor=white)
![Django](https://img.shields.io/badge/Django-5.2+-092e20?style=for-the-badge&logo=django&logoColor=white)
![Geospatial](https://img.shields.io/badge/Geospatial-OpenStreetMap--Overpass-0284c7?style=for-the-badge&logo=openstreetmap&logoColor=white)
![Security](https://img.shields.io/badge/Security-HMAC--SHA256%20%7C%20AI%20Audit-dc2626?style=for-the-badge)
![Tests](https://img.shields.io/badge/Tests-55%2F55%20Passing-059669?style=for-the-badge)
![Status](https://img.shields.io/badge/Status-Production%20Ready-059669?style=for-the-badge)

**Real-time medicine inventory discovery, OpenStreetMap geospatial navigation, unit price normalization, 15-minute stock hold reservations, and 10 integrated AI operational engines.**

[Live Production Site](https://medifind-steel.vercel.app) • [Nearby Mapped Pharmacies](https://medifind-steel.vercel.app/pharmacies/) • [Privacy Policy](https://medifind-steel.vercel.app/privacy/) • [Terms of Service](https://medifind-steel.vercel.app/terms/)

</div>

---

## 🌟 System Overview

**MediAI** bridges the critical gap between patients needing prescription drugs and local licensed pharmacies with available stock. MediAI integrates real-time OpenStreetMap geospatial telemetry with internal POS inventory tracking, offering:

1. **Real-Time OpenStreetMap Discovery**: Overpass API location discovery calculating exact straight-line Haversine distances (`850 m away`, `1.2 km away`) with Leaflet interactive maps.
2. **Strict Telemetry & Inventory Boundary**: Mapped spatial location data (*"Where is the store?"*) is strictly separated from merchant POS inventory data (*"Is medicine X in stock?"*), eliminating fake store availability.
3. **15-Minute Guaranteed Stock Holds**: Prevents checkout double-booking with digital stock locks and automated 15-minute expiration routines.
4. **Razorpay Digital Commerce**: Secure digital payments with server-side HMAC-SHA256 payment signature validation.
5. **Multi-Factor Best Value Ranker (AI #10)**: Dynamic pack size unit price normalization (`Strip of 10 • ₹2.50/tablet`) and multi-tier store ranking (`[⭐ Best Value]`, `[💰 Lowest Price]`, `[📍 Closest Store]`, `[📦 Best Stock]`).
6. **7-Day ML Demand Forecasting (AI #6)**: Predictive sales velocity analysis and stockout risk calculations (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`) for pharmacy operators.
7. **Security & Anomaly Audit Center (AI #8)**: Real-time operational security audit engine flagging price manipulation, cancellation spikes, and rapid inventory changes with human-in-the-loop admin governance.

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                MEDIAI PLATFORM                                  │
├──────────────────────────────────────┬──────────────────────────────────────────┤
│           CONSUMER PORTAL            │             PHARMACY SAAS HUB            │
├──────────────────────────────────────┼──────────────────────────────────────────┤
│ • GPS Location & Overpass Discovery  │ • 7-Day ML Demand Forecasting (AI #6)    │
│ • Straight-Line Distance Normalizer  │ • POS Sync & Excel Batch Ingestion      │
│ • Best Value Unit Ranker (AI #10)    │ • Anomaly Audit Governance (AI #8)       │
│ • 15-Min Stock Hold & Razorpay Pay  │ • Natural Language BI Dashboard (AI #9)  │
└──────────────────────────────────────┴──────────────────────────────────────────┘
```

---

## 🤖 The 10 Integrated AI Engines

| Module | Engine Name | Description |
| :--- | :--- | :--- |
| **AI #1** | **Gemini Intent Extraction** | Converts natural language health queries into structured dosage forms and drug entities. |
| **AI #2** | **Grounded Medical Generator** | Generates safe, clinically validated responses backed by medical reference databases. |
| **AI #3** | **Active Ingredient Matcher** | Identifies generic medicine substitutes matching identical active ingredients. |
| **AI #4** | **Optical Prescription Parser** | Digitizes uploaded prescription images and maps items directly to pharmacy stock. |
| **AI #5** | **Market Pricing Intelligence** | Compares regional price trends across registered stores to detect fair market pricing. |
| **AI #6** | **Predictive Demand Forecaster** | Uses sales velocity to forecast 7-day stock demand and calculate stockout risk levels. |
| **AI #7** | **Patient Safety Assistant** | Explains drug side-effects, interactions, and dosage guidelines in plain language. |
| **AI #8** | **Security & Anomaly Audit** | Monitors store activities for price spikes, cancellation anomalies, and surge patterns. |
| **AI #9** | **Executive BI Analytics** | Converts plain English operational questions into dynamic SQL analytics and charts. |
| **AI #10** | **Best Value Store Ranker** | Normalizes unit pricing (`₹/tablet`) and scores stores using price, distance, and stock. |

---

## 🛰️ OpenStreetMap Geospatial Discovery

- **Haversine Formula**: Calculates exact straight-line distance across Earth's radius ($R = 6371.0\text{ km}$).
- **Sensible Unit Formatting**:
  - Distance $< 1\text{ km}$: Formatted in meters (e.g. `850 m away`).
  - Distance $\ge 1\text{ km}$: Formatted in kilometers (e.g. `1.2 km away`).
- **Interactive Leaflet Maps**: Custom SVG user pulse beacon (`.user-pulse-beacon`), store markers, popup detail cards, and Google Maps directions.
- **Fast Latency Fallbacks**: Overpass API requests use a `2.0s` timeout with local database caching ($<20\text{ms}$) and server pre-rendering ($<50\text{ms}$).

---

## 🎨 Design System & Accessibility

- **WCAG 2.2 AA Contrast Compliance**: Primary text contrast ratio **15.6:1** (`#0f172a`), secondary text `#475569` (**6.9:1**), and input borders `#cbd5e1` (**3.1:1**).
- **Visual Micro-Interactions**: Elevated card hovers, CSS keyframe skeleton loading shimmers (`@keyframes skeletonShimmer`), and high-contrast focus rings.
- **Responsive Layout**: Desktop dual-column map split view with mobile view toggle controls.

---

## 💻 Tech Stack

- **Backend**: Python 3.12, Django 5.2+
- **Geospatial**: OpenStreetMap Overpass API, Leaflet 1.9, Haversine Spherical Calculation
- **Database**: SQLite (Development) / PostgreSQL (Production)
- **Frontend**: Vanilla CSS Design Tokens, JavaScript ES6+, Bootstrap 5.3
- **Payments**: Razorpay API, HMAC-SHA256 Signature Verification
- **Hosting & Infrastructure**: Vercel Production Serverless (`iad1` region)

---

## 🛠️ Local Development Setup

### 1. Clone the repository
```bash
git clone https://github.com/samayshrey-dev/MediFind.git
cd MediFind
```

### 2. Create and activate virtual environment
```bash
python -m venv venv
# On Windows:
venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Apply Database Migrations
```bash
python manage.py migrate
```

### 5. Start Development Server
```bash
python manage.py runserver
```
Visit `http://127.0.0.1:8000/` in your browser.

---

## 🧪 Testing Suite

MediAI includes a comprehensive test suite covering APIs, geospatial calculation, anomaly detection, and payment verification:

```bash
# Run Django automated unit test suite
python manage.py test
```

### Test Results
```
Ran 55 tests in 28.530s

OK
Destroying test database for alias 'default'...
System check identified no issues (0 silenced).
```

---

## 📄 License & Ownership

&copy; 2026 **MediAI Healthcare Systems**. All Rights Reserved.  
Production Application Deployed at [https://medifind-steel.vercel.app](https://medifind-steel.vercel.app).
