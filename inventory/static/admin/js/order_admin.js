document.addEventListener("DOMContentLoaded", function () {
    const productSelect = document.querySelector("#id_products");  // Product multi-select field
    const orderItemContainer = document.querySelector("#orderitem_set-group");  // OrderItem inline formset

    if (productSelect && orderItemContainer) {
        productSelect.addEventListener("change", function () {
            const selectedProductIds = Array.from(productSelect.selectedOptions).map(option => option.value);

            if (selectedProductIds.length > 0) {
                fetch(`/admin/get_variants_from_products/?product_ids=${selectedProductIds.join(",")}`)
                    .then(response => response.json())
                    .then(data => {
                        orderItemContainer.innerHTML = "";  // Clear existing order items

                        data.variants.forEach(variant => {
                            const newRow = document.createElement("div");
                            newRow.innerHTML = `
                                <div>
                                    <label>${variant.variant_code}</label>
                                    <input type="hidden" name="orderitem_set-${variant.id}-product_variant" value="${variant.id}">
                                    <input type="number" name="orderitem_set-${variant.id}-quantity" value="0" min="0">
                                    <input type="number" name="orderitem_set-${variant.id}-item_cost_price" step="0.01">
                                    <input type="date" name="orderitem_set-${variant.id}-date_expected">
                                    <input type="date" name="orderitem_set-${variant.id}-date_arrived">
                                </div>
                            `;
                            orderItemContainer.appendChild(newRow);
                        });
                    });
            }
        });
    }
});
