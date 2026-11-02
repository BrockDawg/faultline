const button = document.getElementById("replay");
button.addEventListener("click", () => {
  fetch("/api/replay-shipped", { method: "POST" });
});
