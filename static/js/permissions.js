(()=>{'use strict';
function spInitPermissions(){
const root=document.querySelector('#permission-editor');if(!root)return;
const data=JSON.parse(document.querySelector('#policy-data').textContent),editable=root.dataset.editable==='1';let user=data.user,busy=false;
const $=id=>document.getElementById(id), el=(tag,text,cls)=>{const n=document.createElement(tag);n.textContent=text;if(cls)n.className=cls;return n;};
$('assigned-role').replaceChildren();$('permission-category').replaceChildren();
$('permission-category').add(new Option('All categories',''));
data.roles.forEach(r=>$('assigned-role').add(new Option(r.name,r.id)));$('assigned-role').value=user.role_id;
[...new Set(data.permissions.map(p=>p.category))].sort().forEach(c=>$('permission-category').add(new Option(c,c)));
function render(){
 const role=data.roles.find(r=>r.id===Number($('assigned-role').value)),roleKeys=new Set(data.permissions.filter(p=>role.permissions.includes(p.id)).map(p=>p.key)),grants=new Set(user.grants),denials=new Set(user.denials),effective=new Set([...roleKeys,...grants].filter(k=>!denials.has(k)));
 $('permission-summary').replaceChildren(...[['Total Permissions',data.permissions.length],['Granted',user.active?effective.size:0],['Denied',denials.size],['Overrides',new Set([...grants,...denials]).size]].map(([label,count])=>{const n=el('div',label);n.append(el('strong',String(count)));return n;}));
 for(const [id,keys] of [['role-permissions',roleKeys],['grant-permissions',grants],['deny-permissions',denials]]){$(id).replaceChildren(...data.permissions.filter(p=>keys.has(p.key)).map(p=>el('div',p.name,'permission-chip'+(denials.has(p.key)?' denied':''))));if(!keys.size)$(id).append(el('p','None','muted'));}
 const q=$('permission-search').value.toLowerCase(),category=$('permission-category').value;
 $('effective-permissions').replaceChildren(...data.permissions.filter(p=>(!category||p.category===category)&&`${p.name} ${p.key}`.toLowerCase().includes(q)).map(p=>{const tr=document.createElement('tr'),name=el('td',p.name);name.append(el('small',p.key,'muted'));tr.append(name,el('td',p.category),el('td',!user.active?'Account disabled':effective.has(p.key)?'✓ Granted':'✕ Denied',effective.has(p.key)&&user.active?'text-success':'text-danger'),el('td',denials.has(p.key)?'Explicit denial':grants.has(p.key)?'Additional grant':roleKeys.has(p.key)?'Role':'Not assigned'));const actions=el('td','','permission-actions');if(editable)for(const [op,label] of [['grant','Grant Permission'],['deny','Deny Permission'],['remove','Remove Override']]){const b=el('button',label,'btn btn-light btn-sm');b.type='button';b.disabled=busy||(op==='remove'&&!grants.has(p.key)&&!denials.has(p.key));b.onclick=()=>update(op,p.id);actions.append(b);}tr.append(actions);return tr;}));
}
async function update(operation,permission_id){if(busy)return;if(Number($('assigned-role').value)!==user.role_id&&operation!=='role'){$('permission-message').textContent='Save the selected role before changing overrides.';return;}if(operation==='reset'&&!confirm('Remove all additional grants and denials for this user?'))return;busy=true;render();try{const response=await fetch(`/api/users/${user.id}/permissions`,{method:'POST',headers:{'Accept':'application/json','Content-Type':'application/json','X-CSRFToken':document.querySelector('meta[name="csrf-token"]').content},body:JSON.stringify({operation,permission_id,role_id:Number($('assigned-role').value),version:user.version})});const result=await response.json();if(!response.ok)throw Error(result.error||result.message||'Unable to update permissions. Refresh and try again.');user=result;$('assigned-role').value=user.role_id;$('permission-message').textContent='Permissions saved. Effective access updated.';}catch(error){$('permission-message').textContent=error.message;}finally{busy=false;render();}}
 $('assigned-role').onchange=()=>{render();$('permission-message').textContent='Role preview — save to apply. Overrides will be preserved.';};$('permission-search').oninput=render;$('permission-category').onchange=render;
 if(editable){$('save-role').onclick=()=>update('role');$('reset-policy').onclick=()=>update('reset');}render();
}
if(document.readyState!=='loading')spInitPermissions();
else document.addEventListener('DOMContentLoaded',spInitPermissions);
document.addEventListener('storepro:content',spInitPermissions);
})();
