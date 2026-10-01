// Recruitment Agent — Client UI Logic

function showToast(message, type = "success") {
    const container = document.getElementById("toast-container");
    if (!container) return;

    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
        <span class="toast-icon">${type === 'success' ? '✓' : '⚠'}</span>
        <span class="toast-message">${message}</span>
    `;

    container.appendChild(toast);

    setTimeout(() => {
        toast.style.transition = "opacity 300ms ease, transform 300ms ease";
        toast.style.opacity = "0";
        toast.style.transform = "translateX(100%)";
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// HTMX Toast Event Listener
document.body.addEventListener("showMessage", function(evt) {
    if (evt.detail && evt.detail.value) {
        showToast(evt.detail.value, evt.detail.type || "success");
    }
});

// Select All Candidates Checkbox helper
function toggleAllCheckboxes(masterCheckbox, targetSelector) {
    const targets = document.querySelectorAll(targetSelector);
    targets.forEach(cb => {
        cb.checked = masterCheckbox.checked;
    });
}
