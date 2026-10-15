const senhaInput = document.getElementById('senhaInput');
const toggleIcon = document.getElementById('toggleIcon');

toggleIcon.addEventListener('click', () => {
    const isPassword = senhaInput.type === 'password';
    senhaInput.type = isPassword ? 'text' : 'password';

    const icon = toggleIcon.querySelector('i');
    icon.classList.toggle('bi-eye', !isPassword);
    icon.classList.toggle('bi-eye-slash', isPassword);
});
