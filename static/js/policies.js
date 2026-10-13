(()=>{'use strict';
function spInitPolicies(){
const rolesEl=document.getElementById('roles-data');if(!rolesEl)return;
const roles=JSON.parse(rolesEl.textContent),select=document.getElementById('policy-role'),message=document.getElementById('policy-message');
const reloadView=()=>{if(window.StorePro&&window.StorePro.reload)window.StorePro.reload();else location.reload();};
async function send(url,data){const response=await fetch(url,{method:'POST',headers:{'Accept':'application/json','Content-Type':'application/json','X-CSRFToken':document.querySelector('meta[name="csrf-token"]').content},body:JSON.stringify(data)});const result=await response.json();if(!response.ok)throw Error(result.error||result.message||'Unable to save. Refresh and try again.');return result;}
function preview(){const role=roles.find(r=>r.id===Number(select.value));document.querySelectorAll('.policy-checks input').forEach(i=>i.checked=role.permissions.includes(Number(i.value)));}
select.onchange=preview;preview();
const searchInput=document.getElementById('role-search');
if(searchInput){searchInput.oninput=e=>{const q=e.target.value.toLowerCase().trim();document.querySelectorAll('.policy-category-block').forEach(block=>{let count=0;block.querySelectorAll('.policy-checks label').forEach(l=>{const m=!q||l.dataset.label.includes(q);l.hidden=!m;if(m)count++;});block.hidden=(count===0);});};}
document.querySelectorAll('.cat-grant-all').forEach(b=>{b.onclick=()=>{const block=b.closest('.policy-category-block');if(block)block.querySelectorAll('.policy-checks input').forEach(i=>i.checked=true);};});
document.querySelectorAll('.cat-revoke-all').forEach(b=>{b.onclick=()=>{const block=b.closest('.policy-category-block');if(block)block.querySelectorAll('.policy-checks input').forEach(i=>i.checked=false);};});
const gAll=document.getElementById('role-grant-all-global');if(gAll)gAll.onclick=()=>document.querySelectorAll('.policy-checks input').forEach(i=>i.checked=true);
const rAll=document.getElementById('role-revoke-all-global');if(rAll)rAll.onclick=()=>document.querySelectorAll('.policy-checks input').forEach(i=>i.checked=false);
document.getElementById('role-policy-form').onsubmit=async e=>{e.preventDefault();const role=roles.find(r=>r.id===Number(select.value));try{const result=await send(`/api/roles/${role.id}/permissions`,{revision:role.revision,permissions:[...document.querySelectorAll('.policy-checks input:checked')].map(i=>Number(i.value))});Object.assign(role,result);message.textContent='Role permissions saved. User overrides remain in effect.';}catch(err){message.textContent=err.message;}};
for(const [id,url] of [['create-role','/api/roles'],['create-permission','/settings/permissions'],['bind-permission','/api/permissions/bindings']])document.getElementById(id).onsubmit=async e=>{e.preventDefault();const data=Object.fromEntries(new FormData(e.target));if(data.permission_id)data.permission_id=Number(data.permission_id);try{await send(url,data);reloadView();}catch(err){message.textContent=err.message;}};
document.querySelectorAll('.remove-binding').forEach(b=>b.onclick=async()=>{try{await send('/api/permissions/bindings',{...JSON.parse(b.dataset.binding),remove:true});reloadView();}catch(err){message.textContent=err.message;}});
}
if(document.readyState!=='loading')spInitPolicies();
else document.addEventListener('DOMContentLoaded',spInitPolicies);
document.addEventListener('storepro:content',spInitPolicies);
})();
