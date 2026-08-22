# MediAI — Real-Time Pharmacy Intelligence & Autonomous Healthcare Commerce

<div align="center">

![MediAI Banner](https://img.shields.io/badge/Platform-MediAI-10b981?style=for-the-badge&logo=mediamarkt&logoColor=white)
![Django](https://img.shields.io/badge/Django-5.0+-092e20?style=for-the-badge&logo=django&logoColor=white)
![Security](https://img.shields.io/badge/Security-Post--Quantum%20Shield-blueviolet?style=for-the-badge)
![Status](https://img.shields.io/badge/Status-Production%20Ready-emerald?style=for-the-badge)

**Real-time medicine inventory discovery, multi-tier ranking, pharmacy ownership verification, and autonomous agentic commerce.**

[Live Production Demo](https://medifind-steel.vercel.app) • [Privacy Policy](https://medifind-steel.vercel.app/privacy/) • [Terms of Service](https://medifind-steel.vercel.app/terms/)

</div>

---

## 🌟 Overview

**MediAI** bridges the critical gap between patients needing prescription drugs and local licensed pharmacies with available stock. Unlike static directory listings or delay-prone delivery apps, MediAI delivers:

1. **Guaranteed In-Stock #1 Ranking Engine**: The top spotlight result is mathematically guaranteed to be in stock at a verified pharmacy.
2. **SKU & Packaging Deduplication**: True packaging variants (e.g. Strip of 15, Strip of 30, Bottle of 100) are grouped into a single pharmacy card with query-level deduplication.
3. **Accurate Store Counting**: "Nearby Options" reflects strict `COUNT(DISTINCT pharmacy)`, displaying physical stores separately from product SKU listings.
4. **Autonomous AI Commerce Agent**: An interactive conversational AI assistant that helps patients locate nearby medicines, compares packaging options, and creates reservations.
5. **Multi-Stage Pharmacy Verification**: 6-stage ownership claim and Form 20/21 Drug Retail License verification workflow before merchants can publish live inventory.
6. **Post-Quantum Cryptography (PQC) Shield**: Quantum-resistant session verification with hybrid Dilithium/Kyber signing simulations and audit trails.
7. **Secure Digital Payments**: Seamless digital transactions powered by Razorpay with real-time merchant settlement.

---

## 🏗️ System Architecture

```
                                    ┌────────────────────────┐
                                    │    Patients / Users    │
                                    └───────────┬────────────┘
                                                │
                                    ┌───────────▼────────────┐
                                    │   MediAI Web & API     │
                                    └─────┬────────────┬─────┘
                                          │            │
             ┌────────────────────────────┴──┐      ┌──┴───────────────────────────┐
             │   Search & Ranking Engine     │      │   Autonomous Commerce Agent   │
             │   1. In-Stock Priority        │      │   - Natural Language Query    │
             │   2. SKU Exactness Scorer     │      │   - SKU Variant Selection     │
             │   3. Haversine Distance       │      │   - One-Click Reservation     │
             │   4. Price Optimization       │      └──────────────────────────────┘
             │   5. Pharmacy Open Status     │
             └──────────────┬────────────────┘
                            │
             ┌──────────────▼────────────────┐
             │    Pharmacy Merchant Portal   │
             │  - Form 20/21 Verification    │
             │  - Stock & SKU Catalog        │
             │  - Live Order Fulfillment     │
             └───────────────────────────────┘
```

---

## 🚀 Key Features

### 🔍 1. 5-Tier Search & Ranking Algorithm
- **Tier 1**: In-stock guarantee (`quantity > 0`). Out-of-stock items are strictly sorted below available inventory.
- **Tier 2**: SKU Exactness (Exact drug name matching > Prefix matching > Generic/Brand matching).
- **Tier 3**: Distance optimization using Haversine spherical distance calculation.
- **Tier 4**: Price ordering for cost transparency.
- **Tier 5**: Live store open/operating status.
- **Zero-Stock Fallback**: When no pharmacies have stock, MediAI presents a clean notification modal: *"No pharmacies currently have [Medicine] in stock."* with restock alerts.

### 🏪 2. Pharmacy Verification & Ownership Claim
- `REGISTER PHARMACY` $\rightarrow$ `CLAIM EXISTING STORE` $\rightarrow$ `VERIFICATION PENDING` $\rightarrow$ `ADMIN REVIEW` $\rightarrow$ `APPROVED` $\rightarrow$ `INVENTORY ACCESS`.
- Form 20/21 Drug Retail License validation, GSTIN checks, and pharmacist registration proofs.
- `@verified_pharmacy_required` security decorator locks publishing capabilities until admin approval.

### 🛡️ 3. Regulatory & Legal Trust
- **Privacy Policy (`/privacy`)**: Full compliance with India's Digital Personal Data Protection Act (DPDP 2023) and global standards.
- **Terms of Service (`/terms`)**: Legally comprehensive terms covering inventory accuracy, customer reservations, merchant obligations, and liability limits.
- **Transparent Payment Messaging**: High-trust copy: *"Secure payments powered by Razorpay"*.

---

## 💻 Tech Stack

- **Backend**: Python 3.12, Django 5.0+
- **Database**: SQLite (Development) / PostgreSQL (Production)
- **Frontend**: Vanilla CSS Design Tokens, JavaScript ES6+, Leaflet Maps, Bootstrap 5.3
- **AI / Agentic Commerce**: MediAI Assistant API with candidate deduplication and conversational workflows
- **Deployment**: Vercel Serverless WSGI / Render Blueprint

---

## 🛠️ Local Development Setup

### 1. Clone the repository
```bash
git clone https://github.com/samayshrey-dev/MediFind.git
cd MediFind
```

### 2. Create and activate a virtual environment
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

### 4. Run migrations
```bash
python manage.py migrate
```

### 5. Start the development server
```bash
python manage.py runserver
```

Visit `http://127.0.0.1:8000/` in your browser.

---

## 🧪 Testing Suite

MediAI includes a comprehensive test suite across ranking, deduplication, verification, and commerce flows:

```bash
# Run all automated test suites
python scratch/test_step7_pharmacy_verification.py
python scratch/test_step6_terms_of_service.py
python scratch/test_step5_privacy_policy.py
python scratch/test_step4_test_mode_messaging.py
python scratch/test_step3_distinct_stores_count.py
python scratch/test_duplicate_listings_deduplication.py
python scratch/test_search_ranking_hierarchy.py
python manage.py test medifind.tests
```

---

## 📄 License & Brand

&copy; 2026 **MediAI**. All Rights Reserved.
Healthcare Technology Platform.
