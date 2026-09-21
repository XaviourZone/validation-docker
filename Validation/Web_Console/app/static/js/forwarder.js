/* Validation Data Forwarder operator panel. */
(function () {
  "use strict";

  const api = (path, options) => fetch(path, Object.assign({headers: {"Content-Type": "application/json"}}, options || {}))
    .then(async r => { const data = await r.json().catch(() => ({})); if (!r.ok) throw new Error(data.error || data.message || `HTTP ${r.status}`); return data; });

  const esc = v => String(v == null ? "" : v).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c]));

  function buildPanel() {
    const view = document.getElementById("view-forwarder");
    if (!view) return;

    view.innerHTML = `
      <div class="fw-head">
        <div><div class="fw-title">Data Forwarder</div><div class="fw-subtitle">Final XML delivery to the Data Diode</div></div>
        <span id="fw-status" class="status-pill stopped">STOPPED</span>
      </div>
      <div class="fw-summary">
        <div><span>Pending</span><strong id="fw-pending">0</strong></div>
        <div><span>Delivered</span><strong id="fw-delivered">0</strong></div>
        <div><span>Retrying</span><strong id="fw-retrying">0</strong></div>
        <div><span>Failed</span><strong id="fw-failed">0</strong></div>
      </div>
      <div class="panel">
        <div class="panel-header"><span class="panel-title">Destinations</span><button class="btn btn-primary" id="fw-add">+ Add Destination</button></div>
        <div class="panel-body" style="padding:0;overflow:auto;">
          <table class="data-table"><thead><tr><th>Name</th><th>Status</th><th>Type</th><th>Folder</th><th>User</th><th>Credential</th><th>Actions</th></tr></thead>
          <tbody id="fw-destinations-body"></tbody></table>
        </div>
      </div>
      <div class="panel">
        <div class="panel-header"><span class="panel-title">Recent Delivery Activity</span></div>
        <div class="panel-body" style="padding:0;overflow:auto;">
          <table class="data-table"><thead><tr><th>Time</th><th>File</th><th>Destination</th><th>State</th><th>Attempts</th><th>Error</th></tr></thead>
          <tbody id="fw-delivery-body"></tbody></table>
        </div>
      </div>
      <div class="modal-backdrop" id="fw-modal">
        <div class="modal-container" style="max-width:700px;">
          <div class="modal-header"><div class="modal-title" id="fw-modal-title">Add Destination</div><button class="modal-close-btn" id="fw-close">✕</button></div>
          <div class="modal-body">
            <input type="hidden" id="fw-editing-name">
            <div class="form-group"><label class="form-label">Destination Name *</label><input id="fw-name" class="form-input" placeholder="D-DIODE-01"></div>
            <div class="form-group"><label class="form-label">Destination Type *</label><select id="fw-protocol" class="form-select"><option value="sftp">Data Diode / SFTP</option><option value="filesystem">FILE / Local Folder</option></select></div>
            <div id="fw-sftp-fields">
              <div class="form-row"><div class="form-group"><label class="form-label">Host / IP *</label><input id="fw-host" class="form-input" placeholder="40.1.1.1"></div><div class="form-group"><label class="form-label">SSH Port</label><input id="fw-port" type="number" class="form-input" value="22" min="1" max="65535"></div></div>
              <div class="form-group"><label class="form-label">SSH Username *</label><input id="fw-user" class="form-input" placeholder="ddiode"></div>
              <div class="form-group"><label class="form-label">SSH Password</label><input id="fw-password" type="password" class="form-input" autocomplete="new-password" placeholder="Enter when not configured"><div id="fw-password-hint" class="form-hint"></div></div>
              <div class="form-group"><label class="form-label">Private Key File (optional)</label><input id="fw-key" class="form-input" placeholder="Leave empty for password authentication"></div>
            </div>
            <div class="form-group">
              <label class="form-label" id="fw-path-label">Remote Folder *</label>
              <div style="display:flex;gap:8px;">
                <input id="fw-path" class="form-input" style="flex:1" placeholder="/home/ddiode/txserver/in/">
                <button type="button" class="btn btn-secondary" id="fw-browse-folder"
                  data-folder-browser-target="fw-path"
                  data-folder-browser-api="/api/router/filesystem/browse"
                  data-folder-browser-title="Select Local Destination Folder">Browse…</button>
              </div>
            </div>
            <div class="form-row"><div class="form-group"><label class="form-label">Connection Timeout</label><input id="fw-timeout" type="number" class="form-input" value="10" min="1"></div><div class="form-group" style="display:flex;align-items:center;padding-top:24px;"><label style="display:flex;align-items:center;gap:8px;font-size:13px;"><input type="checkbox" id="fw-enabled"> Enable</label></div></div>
            <div id="fw-form-error" style="display:none;margin-top:12px;"></div>
          </div>
          <div class="modal-footer"><button class="btn btn-secondary" id="fw-cancel">Cancel</button><button class="btn btn-primary" id="fw-test">Test</button><button class="btn btn-success" id="fw-save">Save</button></div>
        </div>
      </div>`;

    bindControls();
    refresh();
  }

  function setStatus(status) {
    const el=document.getElementById("fw-status"); if(!el)return;
    const s=String(status||"UNKNOWN").toUpperCase();
    el.textContent=s;
    el.className=`status-pill ${s==="RUNNING"?"running":(s==="STARTING"?"degraded":"stopped")}`;
  }
  async function refreshStatus(){try{const d=await api("/api/forwarder/status");setStatus(d.status||"UNKNOWN");}catch(_){setStatus("OFFLINE");}}
  async function refreshMetrics(){try{const d=await api("/api/forwarder/metrics"),states=d.states||{};document.getElementById("fw-pending").textContent=d.pending_files||0;document.getElementById("fw-delivered").textContent=states.DELIVERED||0;document.getElementById("fw-retrying").textContent=states.RETRYING||0;document.getElementById("fw-failed").textContent=states.FAILED||0;}catch(_){}}

  async function refreshDestinations(){
    try{
      const d=await api("/api/forwarder/destinations"),body=document.getElementById("fw-destinations-body");body.innerHTML="";
      (d.destinations||[]).forEach(dest=>{
        const tr=document.createElement("tr");
        tr.innerHTML=`<td><strong>${esc(dest.name)}</strong></td><td><span class="status-pill ${dest.enabled?"running":"stopped"}">${dest.enabled?"ENABLED":"DISABLED"}</span></td><td class="mono">${dest.protocol==="filesystem"?"FILE":"SSH "+esc(dest.host)+":"+esc(dest.port)}</td><td class="mono">${esc(dest.remote_path)}</td><td>${esc(dest.username)}</td><td>${dest.protocol==="filesystem"?"—":(dest.password_configured?"Configured":"Not configured")}</td><td><div class="btn-group"><button class="btn btn-secondary fw-edit" data-name="${esc(dest.name)}">Edit</button><button class="btn btn-secondary fw-test-row" data-name="${esc(dest.name)}">Test</button><button class="btn ${dest.enabled?"btn-danger":"btn-success"} fw-toggle" data-name="${esc(dest.name)}">${dest.enabled?"Disable":"Enable"}</button><button class="btn btn-danger fw-delete" data-name="${esc(dest.name)}">Delete</button></div></td>`;
        body.appendChild(tr);
      });
      body.querySelectorAll(".fw-edit").forEach(b=>b.onclick=()=>openModal((d.destinations||[]).find(x=>x.name===b.dataset.name)));
      body.querySelectorAll(".fw-test-row").forEach(b=>b.onclick=()=>testDestination(b.dataset.name));
      body.querySelectorAll(".fw-toggle").forEach(b=>b.onclick=()=>toggleDestination(b.dataset.name,b.textContent.trim()==="Enable"));
      body.querySelectorAll(".fw-delete").forEach(b=>b.onclick=()=>deleteDestination(b.dataset.name));
    }catch(_){}}
  async function refreshDeliveries(){try{const d=await api("/api/forwarder/deliveries"),body=document.getElementById("fw-delivery-body");body.innerHTML="";(d.deliveries||[]).forEach(x=>{const tr=document.createElement("tr");tr.innerHTML=`<td class="mono">${esc(x.updated_at)}</td><td class="mono">${esc(x.filename)}</td><td>${esc(x.destination)}</td><td>${esc(x.state)}</td><td>${esc(x.attempts)}</td><td>${esc(x.last_error||"")}</td>`;body.appendChild(tr);});}catch(_){}}
  function refresh(){refreshStatus();refreshMetrics();refreshDestinations();refreshDeliveries();}

  function bindControls(){
    document.getElementById("fw-add").onclick=()=>openModal(null);
    document.getElementById("fw-close").onclick=closeModal;
    document.getElementById("fw-cancel").onclick=closeModal;
    document.getElementById("fw-save").onclick=saveDestination;
    document.getElementById("fw-test").onclick=testCurrent;
    document.getElementById("fw-protocol").onchange=updateTypeFields;
  }

  function updateTypeFields(){
    const type=document.getElementById("fw-protocol").value;
    const test=document.getElementById("fw-test");
    const sftp=document.getElementById("fw-sftp-fields");
    const label=document.getElementById("fw-path-label");
    const path=document.getElementById("fw-path");
    const browse=document.getElementById("fw-browse-folder");
    const port=document.getElementById("fw-port");
    const user=document.getElementById("fw-user");
    const pass=document.getElementById("fw-password");
    const key=document.getElementById("fw-key");
    const hint=document.getElementById("fw-password-hint");
    const isFile=type==="filesystem";
    sftp.style.display=isFile?"none":"block";
    label.textContent=isFile?"Local Folder *":"Remote Folder *";
    if (browse) browse.style.display=isFile?"inline-flex":"none";
    path.placeholder=isFile?"C:\\Validation\\XML\\out":"/home/ddiode/txserver/in/";
    port.value=isFile?1:(Number(port.value)||22);
    user.disabled=isFile; pass.disabled=isFile; key.disabled=isFile;
    if(isFile) hint.textContent="XML files will be copied to this local folder.";
    test.textContent=isFile?"Test Folder":"Test SSH";
  }

  function openModal(dest){
    const modal=document.getElementById("fw-modal");
    modal.classList.add("open");
    document.getElementById("fw-modal-title").textContent=dest?"Edit Destination":"Add Destination";
    document.getElementById("fw-editing-name").value=dest?dest.name:"";
    document.getElementById("fw-name").value=dest?dest.name:"";
    document.getElementById("fw-protocol").value=dest?(dest.protocol||"sftp"):"sftp";
    document.getElementById("fw-name").disabled=!!dest;
    document.getElementById("fw-host").value=dest?dest.host:"";
    document.getElementById("fw-port").value=dest?dest.port:22;
    document.getElementById("fw-user").value=dest?dest.username:"";
    document.getElementById("fw-password").value="";
    document.getElementById("fw-path").value=dest?dest.remote_path:"";
    document.getElementById("fw-key").value=dest?dest.private_key_file:"";
    document.getElementById("fw-timeout").value=dest?dest.connect_timeout_seconds:10;
    document.getElementById("fw-enabled").checked=dest?!!dest.enabled:false;

    const hint=document.getElementById("fw-password-hint");
    hint.textContent=dest?(dest.protocol==="filesystem"?"Local file destination; no password required.":(dest.password_configured?"Password already configured. Leave blank to keep it.":"Password is not configured. Enter the Data Diode SSH password before saving.")):"Enter the Data Diode SSH password.";
    updateTypeFields();

    const error=document.getElementById("fw-form-error");error.style.display="none";error.textContent="";error.style.color="";
  }
  function closeModal(){document.getElementById("fw-modal").classList.remove("open");}

  function getDestinationPayload(){
    const protocol=document.getElementById("fw-protocol").value;
    return {
      name:document.getElementById("fw-name").value.trim(),
      enabled:document.getElementById("fw-enabled").checked,
      protocol,
      host:document.getElementById("fw-host").value.trim(),
      port:Number(document.getElementById("fw-port").value),
      username:document.getElementById("fw-user").value.trim(),
      password:document.getElementById("fw-password").value,
      remote_path:document.getElementById("fw-path").value.trim(),
      private_key_file:document.getElementById("fw-key").value.trim(),
      connect_timeout_seconds:Number(document.getElementById("fw-timeout").value),
      verify_remote_size:true
    };
  }

  async function saveDestination(){
    const p=getDestinationPayload(),err=document.getElementById("fw-form-error");
    if(!p.name||!p.remote_path||(p.protocol==="sftp"&&(!p.host||!p.username))){err.textContent=p.protocol==="sftp"?"Name, host, remote folder and SSH username are required.":"Name and local folder are required.";err.style.display="block";return;}
    try{
      const d=await api("/api/forwarder/destinations/save",{method:"POST",body:JSON.stringify(p)});
      if(d.password_required)throw new Error(d.error||"SSH password is required.");
      closeModal();refresh();
    }catch(e){err.textContent=e.message;err.style.display="block";err.style.color="var(--accent-rose)";}
  }

  async function testCurrent(){
    const p=getDestinationPayload(),err=document.getElementById("fw-form-error");
    try{
      if(!p.name||!p.remote_path||(p.protocol==="sftp"&&(!p.host||!p.username)))throw new Error(p.protocol==="sftp"?"Name, host, remote folder and SSH username are required.":"Name and local folder are required.");
      const save=await api("/api/forwarder/destinations/save",{method:"POST",body:JSON.stringify(p)});
      if(save.password_required)throw new Error(save.error||"SSH password is required.");
      const d=await api("/api/forwarder/test",{method:"POST",body:JSON.stringify({name:p.name})});
      err.textContent=d.message||(p.protocol==="sftp"?"SSH connection and remote folder test succeeded.":"Local folder test succeeded.");
      err.style.display="block";err.style.color="var(--accent-emerald)";refresh();
    }catch(e){err.textContent=(p.protocol==="sftp"?"SSH test failed: ":"Folder test failed: ")+e.message;err.style.display="block";err.style.color="var(--accent-rose)";}
  }

  async function testDestination(name){try{const d=await api("/api/forwarder/test",{method:"POST",body:JSON.stringify({name})});alert(d.message||"Destination test succeeded.");}catch(e){alert("Destination test failed: "+e.message);}}
  async function toggleDestination(name,enable){try{await api(`/api/forwarder/destinations/${encodeURIComponent(name)}/${enable?"enable":"disable"}`,{method:"POST",body:"{}"});refresh();}catch(e){alert(e.message);}}
  async function deleteDestination(name){if(!confirm(`Delete Forward Destination '${name}'?`))return;try{await api(`/api/forwarder/destinations/${encodeURIComponent(name)}/delete`,{method:"POST",body:"{}"});refresh();}catch(e){alert(e.message);}}

  function init(){buildPanel();setInterval(()=>{if(!document.hidden)refresh();},3000);}
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init);else init();
})();