const form = document.getElementById("login-form");
const errorBox = document.getElementById("form-error");
const submitBtn = document.getElementById("submit-btn");

// If already signed in, skip straight to the dashboard.
if (getToken()) {
  window.location.href = "index.html";
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  errorBox.style.display = "none";
  submitBtn.disabled = true;
  submitBtn.textContent = "Signing in…";

  const email = document.getElementById("email").value.trim();
  const password = document.getElementById("password").value;

  try {
    await login(email, password);
    window.location.href = "index.html";
  } catch (err) {
    errorBox.textContent = err.message;
    errorBox.style.display = "block";
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "Sign in";
  }
});

document.getElementById("show-register").addEventListener("click", () => {
  window.location.href = "register.html";
});
