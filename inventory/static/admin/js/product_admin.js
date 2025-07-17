// Suggest variant sizes based on selected product type

document.addEventListener('DOMContentLoaded', function () {
    const typeField = document.querySelector('#id_type');
    const sizeInputs = document.querySelectorAll("input[name='variant_sizes']");

    const recommendations = {
        'gi': ['A0','A1','A1L','A2','A2L','A3','A3L','A4'],
        'rg': ['XS','S','M','L','XL'],
        'dk': ['XS','S','M','L','XL'],
        'ck': ['XS','S','M','L','XL']
    };

    function applyRecommendations() {
        const rec = recommendations[typeField.value] || [];
        sizeInputs.forEach(cb => {
            cb.checked = rec.includes(cb.value);
        });
    }

    if (typeField) {
        typeField.addEventListener('change', applyRecommendations);
        applyRecommendations();
    }
});
