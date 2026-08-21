// Home Counter Animation System
document.addEventListener("DOMContentLoaded", function () {
    const counters = document.querySelectorAll(".counter");
    if (!counters.length) return;

    counters.forEach(counter => {
        const target = Number(counter.dataset.target);
        if (isNaN(target) || target <= 0) {
            counter.innerText = counter.dataset.target || "0";
            return;
        }

        let count = 0;
        const speed = Math.max(1, target / 80);

        function updateCounter() {
            if (count < target) {
                count += speed;
                counter.innerText = Math.ceil(count).toLocaleString();
                requestAnimationFrame(updateCounter);
            } else {
                counter.innerText = target.toLocaleString();
            }
        }

        updateCounter();
    });
});