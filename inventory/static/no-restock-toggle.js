(function () {
  const forms = document.querySelectorAll("form[data-no-restock-form]");
  if (!forms.length) {
    return;
  }

  const updateButtonState = (button, isNoRestock) => {
    button.textContent = isNoRestock ? "Undo no restock" : "No restock";
    button.classList.toggle("grey", isNoRestock);
    button.classList.toggle("orange", !isNoRestock);
  };

  forms.forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();

      const submitButton = form.querySelector("[data-no-restock-submit]");
      const stateInput = form.querySelector('input[name="no_restock"]');
      const badge = form
        .closest(".card-panel, .content")
        ?.querySelector("[data-no-restock-badge]");

      if (!submitButton || !stateInput) {
        form.submit();
        return;
      }

      submitButton.disabled = true;

      try {
        const response = await fetch(form.action, {
          method: "POST",
          body: new FormData(form),
          headers: {
            "X-Requested-With": "XMLHttpRequest",
          },
          credentials: "same-origin",
        });

        if (!response.ok) {
          throw new Error(`Request failed: ${response.status}`);
        }

        const payload = await response.json();
        const isNoRestock = Boolean(payload.no_restock);

        stateInput.value = payload.next_no_restock || (isNoRestock ? "0" : "1");
        updateButtonState(submitButton, isNoRestock);

        if (badge) {
          badge.hidden = !isNoRestock;
        }
      } catch (error) {
        form.submit();
      } finally {
        submitButton.disabled = false;
      }
    });
  });
})();
