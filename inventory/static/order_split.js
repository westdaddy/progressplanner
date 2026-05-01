(function (window) {
  const normalizeShares = (shares) => {
    const cleaned = shares.map((value) => {
      const parsed = Number(value);
      return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
    });
    const totalShare = cleaned.reduce((sum, share) => sum + share, 0);
    if (totalShare > 0) {
      return cleaned.map((share) => share / totalShare);
    }
    return cleaned.map(() => (cleaned.length ? 1 / cleaned.length : 0));
  };

  const computeSplit = (totalQuantity, shares) => {
    const total = Math.max(parseInt(totalQuantity, 10) || 0, 0);
    if (!Array.isArray(shares) || !shares.length) {
      return [];
    }

    const normalized = normalizeShares(shares);
    const rows = normalized.map((share, index) => {
      const rawValue = total * share;
      const floorValue = Math.floor(rawValue);
      return {
        index,
        value: floorValue,
        fraction: rawValue - floorValue,
      };
    });

    let remainder = total - rows.reduce((sum, row) => sum + row.value, 0);
    rows.sort((a, b) => b.fraction - a.fraction);

    let index = 0;
    while (remainder > 0 && rows.length) {
      rows[index % rows.length].value += 1;
      remainder -= 1;
      index += 1;
    }

    rows.sort((a, b) => a.index - b.index);
    return rows.map((row) => row.value);
  };

  const applyIdealSplitToModal = (modal) => {
    if (!modal) return;
    const totalInput = modal.querySelector('[data-total-order-input]');
    if (!totalInput) return;
    const inputs = Array.from(modal.querySelectorAll('[data-order-qty-input]'));
    if (!inputs.length) return;

    const shares = inputs.map((input) => input.dataset.sizeShare || '0');
    const split = computeSplit(totalInput.value, shares);
    inputs.forEach((input, index) => {
      const value = split[index] || 0;
      input.value = value > 0 ? value : '';
    });
  };

  const syncTotalFromVariantInputs = (modal) => {
    if (!modal) return;
    const totalInput = modal.querySelector('[data-total-order-input]');
    if (!totalInput) return;
    const total = Array.from(modal.querySelectorAll('[data-order-qty-input]')).reduce((sum, input) => {
      const value = parseInt(input.value, 10);
      return sum + (Number.isFinite(value) && value > 0 ? value : 0);
    }, 0);
    totalInput.value = total > 0 ? String(total) : '';
  };

  window.ProgressPlannerOrderSplit = {
    computeSplit,
    applyIdealSplitToModal,
    syncTotalFromVariantInputs,
  };
})(window);
