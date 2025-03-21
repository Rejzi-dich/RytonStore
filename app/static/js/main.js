// Простой скрипт для копирования команды установки
document.addEventListener('DOMContentLoaded', function() {
    const codeBlocks = document.querySelectorAll('.code-block');
    
    codeBlocks.forEach(block => {
        // Добавляем кнопку копирования
        const copyButton = document.createElement('button');
        copyButton.className = 'btn btn-sm btn-outline-secondary copy-btn';
        copyButton.innerHTML = '<i class="fas fa-copy"></i> Copy';
        copyButton.style.position = 'absolute';
        copyButton.style.right = '10px';
        copyButton.style.top = '10px';
        
        // Делаем блок относительно позиционированным
        block.style.position = 'relative';
        block.appendChild(copyButton);
        
        // Добавляем обработчик клика
        copyButton.addEventListener('click', function() {
            const code = block.querySelector('code').innerText;
            navigator.clipboard.writeText(code).then(() => {
                copyButton.innerHTML = '<i class="fas fa-check"></i> Copied!';
                setTimeout(() => {
                    copyButton.innerHTML = '<i class="fas fa-copy"></i> Copy';
                }, 2000);
            });
        });
    });
});
