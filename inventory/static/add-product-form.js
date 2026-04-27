document.addEventListener('DOMContentLoaded', function () {
  const modalEl = document.getElementById('add-product-modal');
  if (!modalEl) return;

  M.Modal.init(modalEl);

  const form = document.getElementById('add-product-form');
  const steps = Array.from(form.querySelectorAll('.add-product-step'));
  const stepLabel = form.querySelector('[data-step-label]');
  const nextBtn = document.getElementById('add-product-next');
  const backBtn = document.getElementById('add-product-back');
  const saveBtn = document.getElementById('add-product-save');
  const tempIdToggle = document.getElementById('use_temporary_id');
  const productIdField = document.getElementById('product_id');
  const styleField = document.getElementById('style');
  const ageField = document.getElementById('age');
  const addVariantsToggle = document.getElementById('add_variants_toggle');
  const variantBuilder = document.getElementById('variant-builder');
  const variantHint = document.getElementById('variant-hint');
  const variantCheckboxes = document.getElementById('variant-checkboxes');
  const variantInput = document.getElementById('custom_variant_input');
  const addVariantBtn = document.getElementById('add_custom_variant_btn');
  const variantsHiddenInput = document.getElementById('variant_sizes_input');
  const summaryList = document.getElementById('add-product-summary');
  const photoInput = document.getElementById('product_photo_input');
  const photoDropzone = document.getElementById('product-photo-dropzone');
  const photoFilename = document.getElementById('product-photo-filename');

  let step = 1;

  const selectElements = form.querySelectorAll('select');
  M.FormSelect.init(selectElements);

  const variantRecommendations = {
    gi: {
      adult: ['A0', 'A1', 'A1L', 'A2', 'A2L', 'A3', 'A3L', 'A4', 'A5', 'F1', 'F2', 'F3', 'F4'],
      kids: ['M000', 'M00', 'M0', 'M1', 'M2', 'M3', 'M4'],
    },
    ng: {
      adult: ['XS', 'S', 'M', 'L', 'XL', 'XXL'],
      kids: ['KXS', 'KS', 'KM', 'KL', 'KXL'],
    },
    ap: {
      default: ['XS', 'S', 'M', 'L', 'XL'],
    },
    ac: {
      default: [],
    },
  };

  const updatePhotoFilename = () => {
    const selectedFile = photoInput?.files?.[0];
    photoFilename.textContent = selectedFile ? selectedFile.name : 'No file selected';
  };

  const applyDroppedFile = (file) => {
    if (!file || !photoInput) return;
    if (!file.type.startsWith('image/')) {
      M.toast({ html: 'Please drop an image file.' });
      return;
    }
    const transfer = new DataTransfer();
    transfer.items.add(file);
    photoInput.files = transfer.files;
    updatePhotoFilename();
  };

  const setStep = (nextStep) => {
    step = Math.max(1, Math.min(3, nextStep));
    steps.forEach((panel, index) => panel.classList.toggle('is-active', index === step - 1));
    stepLabel.textContent = `Step ${step} of 3`;
    backBtn.disabled = step === 1;
    nextBtn.hidden = step === 3;
    saveBtn.hidden = step !== 3;
  };

  const getSuggestedVariants = () => {
    const style = styleField.value;
    const age = ageField.value;
    const styleMap = variantRecommendations[style] || {};
    return styleMap[age] || styleMap.default || [];
  };

  const renderVariantChecklist = () => {
    const suggestions = getSuggestedVariants();
    variantCheckboxes.innerHTML = '';

    if (styleField.value === 'ac') {
      variantHint.textContent = 'Accessories have no standard size. You can leave variants empty or add custom labels.';
    } else {
      variantHint.textContent = suggestions.length
        ? 'Suggested variants (uncheck any you do not want):'
        : 'Choose category and age to get variant suggestions.';
    }

    suggestions.forEach((variant) => {
      const label = document.createElement('label');
      label.className = 'variant-checkbox';
      label.innerHTML = `<input type="checkbox" class="filled-in" value="${variant}" checked><span>${variant}</span>`;
      variantCheckboxes.appendChild(label);
    });
  };

  const addCustomVariant = () => {
    const value = (variantInput.value || '').trim();
    if (!value) return;

    const existing = Array.from(variantCheckboxes.querySelectorAll('input')).map((i) => i.value.toLowerCase());
    if (existing.includes(value.toLowerCase())) {
      variantInput.value = '';
      return;
    }

    const label = document.createElement('label');
    label.className = 'variant-checkbox';
    label.innerHTML = `<input type="checkbox" class="filled-in" value="${value}" checked><span>${value}</span>`;
    variantCheckboxes.appendChild(label);
    variantInput.value = '';
  };

  const selectedVariants = () => Array.from(variantCheckboxes.querySelectorAll('input:checked')).map((item) => item.value);

  const updateSummary = () => {
    const fields = [
      ['Name', form.product_name.value],
      ['Product ID', form.product_id.value],
      ['Category', styleField.options[styleField.selectedIndex]?.text || '—'],
      ['Type', form.type.options[form.type.selectedIndex]?.text || '—'],
      ['Subtype', form.subtype.options[form.subtype.selectedIndex]?.text || '—'],
      ['Age', ageField.options[ageField.selectedIndex]?.text || '—'],
      ['Restock time', form.restock_time.value ? `${form.restock_time.value} months` : 'Not set'],
      ['Variants', addVariantsToggle.checked ? (selectedVariants().join(', ') || 'None selected') : 'Not added'],
    ];

    summaryList.innerHTML = fields
      .map(([label, value]) => `<li class="collection-item"><strong>${label}:</strong> ${value || '—'}</li>`)
      .join('');
  };

  tempIdToggle.addEventListener('change', function () {
    if (tempIdToggle.checked) {
      productIdField.value = 'TEMP (auto-assigned)';
      productIdField.readOnly = true;
      M.updateTextFields();
    } else {
      productIdField.readOnly = false;
      productIdField.value = '';
      M.updateTextFields();
    }
  });

  [styleField, ageField].forEach((field) => field.addEventListener('change', renderVariantChecklist));

  addVariantsToggle.addEventListener('change', function () {
    variantBuilder.hidden = !addVariantsToggle.checked;
    if (addVariantsToggle.checked) renderVariantChecklist();
  });

  addVariantBtn.addEventListener('click', addCustomVariant);
  variantInput.addEventListener('keydown', function (event) {
    if (event.key === 'Enter') {
      event.preventDefault();
      addCustomVariant();
    }
  });

  backBtn.addEventListener('click', () => setStep(step - 1));

  nextBtn.addEventListener('click', () => {
    if (step === 1 && !form.product_name.value.trim()) {
      M.toast({ html: 'Please add a product name.' });
      return;
    }

    if (step === 1 && !tempIdToggle.checked && !form.product_id.value.trim()) {
      M.toast({ html: 'Please add a product ID or choose temporary ID.' });
      return;
    }

    if (step === 2) {
      if (!styleField.value) {
        M.toast({ html: 'Please choose a product category.' });
        return;
      }
      updateSummary();
    }

    setStep(step + 1);
  });

  form.addEventListener('submit', function () {
    variantsHiddenInput.value = addVariantsToggle.checked ? selectedVariants().join(',') : '';
  });

  if (photoDropzone && photoInput) {
    photoDropzone.addEventListener('click', () => photoInput.click());
    photoDropzone.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        photoInput.click();
      }
    });

    ['dragenter', 'dragover'].forEach((eventName) => {
      photoDropzone.addEventListener(eventName, (event) => {
        event.preventDefault();
        photoDropzone.classList.add('is-drag-active');
      });
    });

    ['dragleave', 'drop'].forEach((eventName) => {
      photoDropzone.addEventListener(eventName, (event) => {
        event.preventDefault();
        photoDropzone.classList.remove('is-drag-active');
      });
    });

    photoDropzone.addEventListener('drop', (event) => {
      const droppedFile = event.dataTransfer?.files?.[0];
      applyDroppedFile(droppedFile);
    });

    photoInput.addEventListener('change', updatePhotoFilename);
  }

  setStep(1);
});
