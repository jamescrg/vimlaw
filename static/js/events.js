
function toggleCalculator() {
    const div = document.querySelector('#deadline-calculator-form');
    if (div.style.display === 'block') {
        div.style.display = 'none';
    } else {
        div.style.display = 'block';
    }
}
