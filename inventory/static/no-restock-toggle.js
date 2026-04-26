(function () {
  const toggleForms = document.querySelectorAll("form[data-product-toggle-form]");
  const legacyNoRestockForms = document.querySelectorAll("form[data-no-restock-form]");

  if (!toggleForms.length && !legacyNoRestockForms.length) {
    return;
  }

  const setToggleVisualState = (button, isOn) => {
    if (!button) {
      return;
    }
    button.classList.toggle("is-on", isOn);
    button.setAttribute("aria-pressed", isOn ? "true" : "false");
  };

  const submitToggleFormAsync = async (form, stateInput, button) => {
    button.disabled = true;

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
      const isOn = Boolean(payload.state);
      stateInput.value = payload.next_state || (isOn ? "0" : "1");
      setToggleVisualState(button, isOn);
    } catch (error) {
      form.submit();
    } finally {
      button.disabled = false;
    }
  };

  toggleForms.forEach((form) => {
    const button = form.querySelector("[data-toggle-button]");
    const stateInput = form.querySelector("[data-toggle-state-input]");

    if (!button || !stateInput) {
      return;
    }

    const submitHandler = (event) => {
      event.preventDefault();
      submitToggleFormAsync(form, stateInput, button);
    };

    button.addEventListener("click", submitHandler);
    form.addEventListener("submit", submitHandler);
  });

  legacyNoRestockForms.forEach((form) => {
    if (form.hasAttribute("data-product-toggle-form")) {
      return;
    }

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
        submitButton.textContent = isNoRestock ? "Undo no restock" : "No restock";
        submitButton.classList.toggle("grey", isNoRestock);
        submitButton.classList.toggle("orange", !isNoRestock);

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
