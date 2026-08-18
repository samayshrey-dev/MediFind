// ============================================
// MediFind Live Notifications System
// ============================================

let lastNotificationId = 0;
let firstLoad = true;

const badge = document.getElementById("notification-count");
const list = document.getElementById("notification-list");

function fetchNotifications() {
    fetch("/notifications/")
    .then(response => response.json())
    .then(notifications => {
        updateBadge(notifications);
        updateDropdown(notifications);
        checkForNewNotification(notifications);
    })
    .catch(error => {
        console.log("Notification Fetch Error:", error);
    });
}

// ============================================
// Notification Badge Counter
// ============================================
function updateBadge(notifications) {
    if (!badge) return;
    const unread = notifications.filter(n => !n.is_read).length;
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
    if (!list) return;

    list.innerHTML = `
        <li class="dropdown-header fw-bold">
            <i class="fa-solid fa-bell me-2"></i>Notifications
        </li>
        <li><hr class="dropdown-divider m-0"></li>
    `;

    if (notifications.length === 0) {
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
// Detect & Trigger New Notifications
// ============================================
function checkForNewNotification(notifications) {
    if (!notifications || notifications.length === 0) return;

    const newest = notifications[0];
    const newestId = newest.id;

    // First load on page render
    if (firstLoad) {
        firstLoad = false;
        lastNotificationId = newestId;

        // If the newest notification is unread AND created recently ("Just now" or "< 1 min"), pop up bottom-right toast & play sound
        if (!newest.is_read && (newest.time === "Just now" || newest.time.includes("min"))) {
            animateBell();
            playNotificationSound();
            showToast(newest);
        }
        return;
    }

    // New notification arrived via live polling
    if (newestId > lastNotificationId) {
        lastNotificationId = newestId;
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
// Bell Animation
// ============================================
function animateBell() {
    const bell = document.querySelector(".fa-bell");
    if (!bell) return;
    bell.classList.add("bell-shake");
    setTimeout(() => {
        bell.classList.remove("bell-shake");
    }, 800);
}

// ============================================
// Audio Sound Effect
// ============================================
function playNotificationSound() {
    try {
        const audio = new Audio("/static/sounds/notification.mp3");
        audio.volume = 0.5;
        const promise = audio.play();
        if (promise !== undefined) {
            promise.catch(err => {
                console.log("Audio playback waiting for user interaction:", err);
            });
        }
    } catch (e) {
        console.log("Audio error:", e);
    }
}

// ============================================
// Initialize Real-Time Polling Loop
// ============================================
document.addEventListener("DOMContentLoaded", () => {
    fetchNotifications();
    setInterval(fetchNotifications, 2000);
});