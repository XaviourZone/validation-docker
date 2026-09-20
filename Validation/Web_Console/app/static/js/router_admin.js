/* Router administration extension: operator-facing source management and parser mapping. */
(function () {
  "use strict";
  const esc=v=>String(v==null?"":v).replace(/[&<>\"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c]));
  const api=(url,options)=>fetch(url,Object.assign({headers:{"Content-Type":"application/json"}},options||{})).then(async r=>{const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.error||d.message||`HTTP ${r.status}`);return d;});

  function installFetchReload(){
    if(window.__validationRouterReloadPatch)return;
    window.__validationRouterReloadPatch=true;
    const original=window.fetch.bind(window);
    window.fetch=async function(input,init){
      const response=await original(input,init);
      const url=typeof input==="string"?input:(input&&input.url)||"";
      if(response.ok&&(url==="/api/router/sources/save"||/^\/api\/router\/sources\/.+\/(delete|enable|disable)$/.test(url))){
        original("/api/router/reload",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"}).catch(()=>{});
      }
      return response;
    };
  }

  function simplifySourceForm(){
    ["src-stability","src-poll","src-framing","src-max-line","src-recon-init","src-recon-max"].forEach(id=>{
      const input=document.getElementById(id); if(!input)return;
      const group=input.closest(".form-group"); if(group)group.style.display="none"; else input.style.display="none";
    });
    const pending=document.querySelector(".pending-spec-banner"); if(pending)pending.style.display="none";
    const folder=document.getElementById("src-folder"); if(folder){const h=folder.parentElement?.querySelector(".form-hint");if(h)h.textContent="Select the folder containing incoming files.";}
    const patterns=document.getElementById("src-patterns"); if(patterns){const h=patterns.parentElement?.querySelector(".form-hint");if(h)h.textContent="Choose the files to process.";}
  }

  function installMappingPanel(){
    const parserView=document.getElementById("view-parser"); if(!parserView||document.getElementById("btn-parser-mapping"))return;
    const holder=document.createElement("div");holder.style.cssText="margin:0 0 14px;display:flex;justify-content:flex-end;";
    holder.innerHTML='<button class="btn btn-primary" id="btn-parser-mapping">Parser Mapping · 41 Fields</button>';parserView.insertBefore(holder,parserView.firstElementChild||null);
    document.getElementById("btn-parser-mapping").onclick=openMapping;
  }

  async function openMapping(selectName){
    let modal=document.getElementById("parser-mapping-modal");
    if(!modal){
      modal=document.createElement("div");modal.id="parser-mapping-modal";modal.className="modal-backdrop open";modal.style.zIndex="10040";
      modal.innerHTML=`<div class="modal-container" style="max-width:1200px;width:96vw;max-height:92vh;"><div class="modal-header"><div class="modal-title">Parser Mapping · 41 XML Fields</div><button class="modal-close-btn" id="pm-close">✕</button></div><div class="modal-body" style="overflow:auto;"><div class="form-group"><label class="form-label">Parser</label><select id="pm-parser" class="form-input"></select></div><div style="overflow:auto;"><table class="data-table"><thead><tr><th>#</th><th>XML Field</th><th>Priority 1</th><th>Priority 2</th><th>Priority 3</th><th>Priority 4</th><th>Priority 5</th></tr></thead><tbody id="pm-body"></tbody></table></div></div><div class="modal-footer"><button class="btn btn-secondary" id="pm-cancel">Cancel</button><button class="btn btn-success" id="pm-save">Save</button></div></div>`;
      document.body.appendChild(modal);document.getElementById("pm-close").onclick=()=>modal.remove();document.getElementById("pm-cancel").onclick=()=>modal.remove();
    }
    const sel=document.getElementById("pm-parser"),p=await api("/api/parser/mapping/parsers");sel.innerHTML="";(p.parsers||[]).forEach(n=>{const o=document.createElement("option");o.value=n;o.textContent=n;sel.appendChild(o);});
    if(selectName&&[...sel.options].some(o=>o.value===selectName))sel.value=selectName;
    sel.onchange=loadMapping;await loadMapping();
    async function loadMapping(){
      const name=sel.value;if(!name)return;const [d,f]=await Promise.all([api("/api/parser/mapping?parser="+encodeURIComponent(name)),api("/api/parser/mapping/fields")]);const body=document.getElementById("pm-body");body.innerHTML="";
      (f.fields||[]).forEach((field,i)=>{const vals=((d.mapping.fields||{})[field]||[]).slice(0,5);while(vals.length<5)vals.push("");const tr=document.createElement("tr");tr.innerHTML=`<td>${i+1}</td><td class="mono">${esc(field)}</td>`+vals.map(v=>`<td><input class="form-input pm-candidate" data-field="${esc(field)}" value="${esc(v)}" placeholder="field name"></td>`).join("");body.appendChild(tr);});
    }
    document.getElementById("pm-save").onclick=async()=>{const fields={};document.querySelectorAll(".pm-candidate").forEach(i=>{const v=i.value.trim();fields[i.dataset.field]=fields[i.dataset.field]||[];if(v)fields[i.dataset.field].push(v);});try{await api("/api/parser/mapping/save",{method:"POST",body:JSON.stringify({parser:sel.value,mapping:{format:"auto",fields}})});modal.remove();alert("Parser mapping saved.");}catch(e){alert(e.message);}};
  }

  function boot(){installFetchReload();simplifySourceForm();installMappingPanel();setTimeout(()=>{simplifySourceForm();installMappingPanel();},500);}
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",boot);else boot();
})();