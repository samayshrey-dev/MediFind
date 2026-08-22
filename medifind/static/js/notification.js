// ============================================
// MediAI Live Notifications System (Pop-once guarantee)
// ============================================

let lastNotificationId = parseInt(localStorage.getItem("mediai_last_toasted_id") || localStorage.getItem("medifind_last_toasted_id") || "0", 10);
let firstLoad = true;

function fetchNotifications() {
    // Only poll if user is authenticated and notification dropdown exists
    const bellContainer = document.getElementById("notificationDropdown");
    if (!bellContainer) return;

    fetch("/notifications/")
    .then(response => {
        if (!response.ok) return null;
        return response.json();
    })
    .then(notifications => {
        if (!notifications) return;
        updateBadge(notifications);
        updateDropdown(notifications);
        checkForNewNotification(notifications);
    })
    .catch(error => {
        // Silently handle network drops during background polling
    });
}

// ============================================
// Notification Badge Counter
// ============================================
function updateBadge(notifications) {
    const badge = document.getElementById("notification-count");
    if (!badge) return;
    const unread = Array.isArray(notifications) ? notifications.filter(n => !n.is_read).length : 0;
    if (unread > 0) {
        badge.style.display = "flex";
        badge.innerText = unread;
    } else {
        badge.style.display = "none";
    }
}

// ============================================
// Notification Dropdown Menu
// ============================================
function updateDropdown(notifications) {
    const list = document.getElementById("notification-list");
    if (!list) return;

    list.innerHTML = `
        <li class="dropdown-header fw-bold">
            <i class="fa-solid fa-bell me-2"></i>Notifications
        </li>
        <li><hr class="dropdown-divider m-0"></li>
    `;

    if (!Array.isArray(notifications) || notifications.length === 0) {
        list.innerHTML += `
            <li class="text-center text-muted py-4">
                <i class="fa-regular fa-bell-slash fs-4 d-block mb-2 text-secondary"></i>
                No notifications yet
            </li>
        `;
        return;
    }

    notifications.forEach(notification => {
        list.innerHTML += `
        <li>
            <a href="#" class="dropdown-item py-3 ${notification.is_read ? '' : 'bg-light'}">
                <div class="fw-bold mb-1 d-flex justify-content-between align-items-center">
                    <span>${notification.title}</span>
                    <span class="badge ${notification.type === 'Accepted' ? 'bg-success' : notification.type === 'Rejected' ? 'bg-danger' : 'bg-primary'} rounded-pill" style="font-size: 10px;">${notification.type}</span>
                </div>
                <div class="small text-dark mb-1">
                    ${notification.message}
                </div>
                <small class="text-muted">
                    <i class="fa-regular fa-clock me-1"></i>${notification.time}
                </small>
            </a>
        </li>
        <li><hr class="dropdown-divider m-0"></li>
        `;
    });
}

// ============================================
// Detect & Trigger New Notifications (Strict Single Pop)
// ============================================
function checkForNewNotification(notifications) {
    if (!Array.isArray(notifications) || notifications.length === 0) return;

    const newest = notifications[0];
    const newestId = newest.id;

    // First load on page render: calibrate highest existing notification without toasting
    if (firstLoad) {
        firstLoad = false;
        if (newestId > lastNotificationId) {
            lastNotificationId = newestId;
            localStorage.setItem("mediai_last_toasted_id", String(newestId));
        }
        return;
    }

    // New notification arrived in real-time via live polling
    const storedLastId = parseInt(localStorage.getItem("mediai_last_toasted_id") || localStorage.getItem("medifind_last_toasted_id") || "0", 10);
    if (newestId > lastNotificationId && newestId > storedLastId) {
        lastNotificationId = newestId;
        localStorage.setItem("mediai_last_toasted_id", String(newestId));
        animateBell();
        playNotificationSound();
        showToast(newest);
    }
}

// ============================================
// Toast Notification (Bottom Right Popup)
// ============================================
function showToast(notification) {
    const oldToast = document.querySelector(".notification-toast");
    if (oldToast) {
        oldToast.remove();
    }

    const toast = document.createElement("div");
    toast.className = "notification-toast";

    const icon = notification.type === "Accepted" ? "fa-circle-check text-success" :
                 notification.type === "Rejected" ? "fa-circle-xmark text-danger" : "fa-bell text-info";

    toast.innerHTML = `
        <div class="toast-title">
            <i class="fa-solid ${icon} fs-5 me-1"></i> ${notification.title}
        </div>
        <div class="toast-message">
            ${notification.message}
        </div>
    `;

    document.body.appendChild(toast);

    setTimeout(() => {
        toast.classList.add("show");
    }, 100);

    setTimeout(() => {
        toast.classList.remove("show");
        setTimeout(() => {
            toast.remove();
        }, 400);
    }, 6000);
}

// ============================================
// Bell Shake Animation
// ============================================
function animateBell() {
    const bell = document.querySelector("#notificationDropdown i");
    if (bell) {
        bell.classList.add("bell-shake");
        setTimeout(() => {
            bell.classList.remove("bell-shake");
        }, 1000);
    }
}

// ============================================
// Notification Sound
// ============================================
function playNotificationSound() {
    try {
        const audio = new Audio("https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3");
        audio.volume = 0.5;
        audio.play().catch(() => {});
    } catch (e) {}
}

// Initial Fetch and Background Polling every 15s
document.addEventListener("DOMContentLoaded", () => {
    fetchNotifications();
    setInterval(fetchNotifications, 15000);
});