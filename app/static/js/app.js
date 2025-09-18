async function copyToClipboard(text){try{await navigator.clipboard.writeText(text);showToast("Link copiado ✔")}catch(e){showToast("Falha ao copiar")}}
function showToast(msg){const t=document.getElementById("toast"); if(!t) return; t.textContent=msg; t.style.display="block"; setTimeout(()=> t.style.display="none", 2000);}
function openAndSuggestPrint(url){window.open(url + "#view=FitH&toolbar=1", "_blank","noopener");}
function filterCards(){const q=(document.getElementById("q").value||"").toLowerCase();document.querySelectorAll(".study-card").forEach(c=>{const hay=(c.getAttribute("data-hay")||"").toLowerCase();c.style.display=hay.includes(q)?"":"none";});}
async function printDirect(url){try{const r=await fetch(url,{method:"POST"}); if(r.ok){showToast("Enviado à impressora ✔")} else {showToast("Falha ao imprimir");}}catch(e){showToast("Erro ao imprimir")}}
