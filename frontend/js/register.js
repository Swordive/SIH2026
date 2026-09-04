const form = document.getElementById("register-form");
const errorBox = document.getElementById("form-error");
const submitBtn = document.getElementById("submit-btn");

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  errorBox.style.display = "none";
  submitBtn.disabled = true;
  submitBtn.textContent = "Creating account…";

  const payload = {
    full_name: document.getElementById("full_name").value.trim(),
    email: document.getElementById("email").value.trim(),
    password: document.getElementById("password").value,
    role: document.getElementById("role").value,
    organization: document.getElementById("organization").value.trim() || null,
  };

  try {
    await apiFetch("/api/auth/register", { method: "POST", body: payload, auth: false });
    await login(payload.email, payload.password);
    window.location.href = "index.html";
  } catch (err) {
    errorBox.textContent = err.message;
    errorBox.style.display = "block";
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "Create account";
  }
});

document.getElementById("show-login").addEventListener("click", () => {
  window.location.href = "login.html";
});
