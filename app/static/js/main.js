/**
 * Smart Emergency Drone Delivery System - UI Controller (Vanilla JavaScript)
 */

document.addEventListener("DOMContentLoaded", () => {
  // 1. Alert Dismissal Handler
  document.querySelectorAll(".alert-close").forEach((button) => {
    button.addEventListener("click", (e) => {
      const alert = e.target.closest(".alert");
      if (alert) {
        alert.style.opacity = "0";
        alert.style.transition = "opacity 0.2s ease";
        setTimeout(() => alert.remove(), 200);
      }
    });
  });

  // 2. Prevent Double Submissions & Display Loading Indicator
  document.querySelectorAll("form").forEach((form) => {
    form.addEventListener("submit", (e) => {
      const submitBtn = form.querySelector("button[type='submit']");
      if (submitBtn && !submitBtn.disabled) {
        submitBtn.dataset.originalText = submitBtn.innerText;
        submitBtn.disabled = true;
        submitBtn.innerText = "Processing...";
        // Re-enable after 6 seconds safety fallback in case submission is halted
        setTimeout(() => {
          submitBtn.disabled = false;
          submitBtn.innerText = submitBtn.dataset.originalText || "Submit";
        }, 6000);
      }
    });
  });
});
