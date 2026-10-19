// Copy buttons (ActuNode Cloud): <button data-copy="text">. Served from this site only (CSP script-src 'self').
document.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-copy]");
  if (!button) return;
  navigator.clipboard.writeText(button.dataset.copy).then(() => {
    const label = button.textContent;
    button.textContent = "Copied";
    setTimeout(() => (button.textContent = label), 1500);
  });
});
