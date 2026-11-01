/* Snapshot imports stay in the tab. Optional collection talks only to our loopback helper. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id), Core=OCIExplorer;
  const labels={adb:'Autonomous DB',oic:'Integration',bucket:'Bucket'}, icons={adb:'▤',oic:'⌘',bucket:'▱'};
  let model, selected=null, expanded=new Set(), page=0, sort='name', direction=1, shown=[], currentResource=null, demo=true;
  const pageSize=30;
  function element(tag,cls,text){const el=document.createElement(tag);if(cls)el.className=cls;if(text!==undefined)el.textContent=text;return el;}
  function message(text,success=false){$('message').textContent=text;$('message').hidden=!text;$('message').className='message'+(success?' success':'');}
  function filterValues(){return {ocid:$('ocid').value,name:$('name-pattern').value,kind:$('kind').value,region:$('region').value,state:$('state').value,exact:$('exact').checked};}
  function populateSelect(id,values,all,format=v=>v){const el=$(id);el.replaceChildren(new Option(all,''));for(const v of [...new Set(values)].sort())el.add(new Option(format(v),v));}
  function load(data,label,isDemo){
    const next=Core.normalize(data); // Validate fully before replacing a working inventory.
    model=next;demo=isDemo;selected=null;expanded=new Set(model.order.filter(id=>model.nodes.get(id).depth<3));page=0;
    populateSelect('kind',model.resources.map(r=>r.kind),'All types',v=>labels[v] || v);
    populateSelect('region',model.resources.map(r=>r.region),'All regions');
    populateSelect('state',model.resources.map(r=>r.state || 'Not reported'),'All states');
    $('ocid').value='';$('name-pattern').value='';$('exact').checked=false;$('descendants').checked=true;
    $('tenancy-name').textContent=model.data.tenancy.name || model.data.tenancy.id;
    $('source-label').textContent=isDemo?'DEMO SNAPSHOT':'IMPORTED SNAPSHOT';
    const timestamp=model.data.collected_at, date=timestamp?new Date(timestamp):null;
    $('snapshot-date').textContent=label+' · '+(date && !isNaN(date)?'Collected '+date.toLocaleString():'Collection time unavailable');
    $('stat-resources').textContent=model.resources.length.toLocaleString();
    $('stat-compartments').textContent=model.nodes.size.toLocaleString();
    const regions=model.data.coverage?.regions || [...new Set(model.resources.map(r=>r.region))];
    $('stat-regions').textContent=regions.length;$('stat-types').textContent=new Set(model.resources.map(r=>r.kind)).size;
    const subscribed=(model.data.regions || []).filter(r=>r.status==='READY').map(r=>r.region_name);
    const unscanned=subscribed.filter(r=>!regions.includes(r));
    $('coverage').textContent=(isDemo?'Synthetic data for exploration':'File processed in this browser')+' · '+(unscanned.length?unscanned.length+' subscribed region(s) not scanned':'Snapshot scope applies');
    $('coverage').title='Scanned regions: '+regions.join(', ')+(unscanned.length?'\nNot scanned: '+unscanned.join(', '):'')+(model.data.coverage?.scans?'\nMerged snapshot: each region may have a different service/compartment scope.':'');
    $('region-caption').textContent=unscanned.length?unscanned.length+' subscribed region(s) outside scope':'from snapshot coverage';
    message(model.data.coverage?.incomplete?'This snapshot reports incomplete collection. Counts cover only imported records.':'');
    if($('details').open)$('details').close();
    render();
  }
  function selectCompartment(id){selected=id;page=0;render();}
  function renderTree(globalRows){
    const counts=Core.matchCounts(model,globalRows), filtered=Object.values(filterValues()).some(Boolean);
    $('all-count').textContent=globalRows.length+' / '+model.resources.length;
    $('all-compartments').classList.toggle('selected',selected===null);
    const container=$('tree'), fragment=document.createDocumentFragment(), visible=new Set();
    for(const id of model.order){
      const n=model.nodes.get(id);if(model.nodes.has(n.compartment_id) && (!visible.has(n.compartment_id) || !expanded.has(n.compartment_id)))continue;
      visible.add(id);
      const row=element('div','tree-row'+(id===selected?' selected':''));row.style.paddingLeft=Math.min(n.depth,12)*15+'px';
      const toggle=element('button','toggle',expanded.has(id)?'▾':'▸');toggle.disabled=!n.children.length;toggle.setAttribute('aria-label',(expanded.has(id)?'Collapse ':'Expand ')+n.name);toggle.setAttribute('aria-expanded',String(expanded.has(id)));toggle.onclick=()=>{expanded.has(id)?expanded.delete(id):expanded.add(id);renderTree(globalRows);};
      const button=element('button','node-button');button.title=n.path+'\n'+n.own.length+' directly here · '+n.descendants+' in children · '+n.total+' total';button.setAttribute('aria-current',id===selected?'true':'false');button.onclick=()=>selectCompartment(id);
      button.append(element('span','folder',n.unresolved?'◇':'▱'),element('span','node-name',n.name),element('span','node-count',(filtered?counts.get(id)+' / ':'')+n.total));
      row.append(toggle,button);fragment.append(row);
    }
    container.replaceChildren(fragment);
  }
  function render(){
    const globalRows=Core.query(model,filterValues()), scope=Core.subtreeIds(model,selected,$('descendants').checked);
    shown=globalRows.filter(r=>scope.has(r.compartment_id));
    const collator=new Intl.Collator(undefined,{numeric:true,sensitivity:'base'});
    shown.sort((a,b)=>direction*(collator.compare(String(a[sort] || ''),String(b[sort] || '')) || a.key.localeCompare(b.key)));
    page=Math.min(page,Math.max(0,Math.ceil(shown.length/pageSize)-1));
    renderTree(globalRows);
    const node=model.nodes.get(selected);$('scope-name').textContent=node?node.name:'Entire snapshot';$('scope-path').textContent=node?node.path:'All collected compartments and regions';
    $('result-summary').textContent=shown.length.toLocaleString()+' matching resource'+(shown.length===1?'':'s')+' · '+(node?($('descendants').checked?node.total:node.own.length):model.resources.length)+' in scope';
    const body=$('results'), fragment=document.createDocumentFragment(), slice=shown.slice(page*pageSize,(page+1)*pageSize);
    for(const r of slice){
      const row=element('tr'), nameCell=element('td'), button=element('button','resource-name');button.onclick=()=>showDetails(r);
      const name=element('span');name.append(element('span','resource-text',r.name),element('span','resource-ocid',r.id));
      button.append(element('span','resource-icon '+r.kind,icons[r.kind] || '◇'),name);nameCell.append(button,element('div','resource-path',r.path));
      const typeCell=element('td');typeCell.append(element('span','type-badge',labels[r.kind] || r.kind));
      const stateCell=element('td');const state=r.state || 'Not reported';const stateClass=/FAILED|UNAVAILABLE|INACCESSIBLE/.test(state)?' failed':/STOP|TERMINAT|DELET|PROVISION|UPDAT/.test(state)?' warning':!r.state?' neutral':'';stateCell.append(element('span','state-badge'+stateClass,state));
      const actionCell=element('td'), open=element('button','open-detail','↗');open.setAttribute('aria-label','View details for '+r.name);open.onclick=()=>showDetails(r);actionCell.append(open);
      row.append(nameCell,typeCell,element('td','region-cell',r.region),stateCell,actionCell);fragment.append(row);
    }
    body.replaceChildren(fragment);$('empty').hidden=shown.length>0;
    $('page-info').textContent=shown.length?`${page*pageSize+1}–${Math.min((page+1)*pageSize,shown.length)} of ${shown.length} resources`:'0 resources';
    $('previous').disabled=page===0;$('next').disabled=(page+1)*pageSize>=shown.length;$('export').disabled=!shown.length;
    for(const b of document.querySelectorAll('[data-sort]')){b.parentElement.setAttribute('aria-sort',b.dataset.sort===sort?(direction===1?'ascending':'descending'):'none');b.querySelector('span').textContent=b.dataset.sort===sort?(direction===1?'↑':'↓'):'↕';}
  }
  function showDetails(r){
    currentResource=r;$('detail-name').textContent=r.name;$('detail-fields').replaceChildren();
    for(const [label,value] of [['OCID / reporting ID',r.id],['Type',labels[r.kind] || r.kind],['Compartment',r.path],['Compartment OCID',r.compartment_id],['Region',r.region],['State',r.state || 'Not reported']]){
      const field=element('div','detail-field');field.append(element('span','',label),element(label.includes('ID')?'code':'div','',value));$('detail-fields').append(field);
    }
    const {key,path,...original}=r;$('detail-json').textContent=JSON.stringify(original,null,2);$('copy-ocid').textContent='Copy OCID';$('details').showModal();
  }
  async function readFile(file){
    if(!file)return;
    try{
      if(file.size>100*1024*1024)throw Error('Snapshot exceeds the 100 MB browser import limit. Use a scoped inventory.');
      const bytes=new Uint8Array(await file.arrayBuffer());
      const encoding=bytes[0]===255 && bytes[1]===254?'utf-16le':bytes[0]===254 && bytes[1]===255?'utf-16be':'utf-8';
      const content=new TextDecoder(encoding,{fatal:true}).decode(bytes);
      load(JSON.parse(content),file.name,false);
    }catch(error){message('Could not open snapshot: '+error.message);}
    $('file').value='';
  }
  $('file').onchange=e=>readFile(e.target.files[0]);
  $('open-file').onclick=()=>$('file').click();
  function downloadJSON(value,filename){const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));const a=element('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  $('save-snapshot').onclick=()=>downloadJSON(model.data,'oci-snapshot-'+(model.data.collected_at || 'undated').replace(/[^a-zA-Z0-9-]/g,'-')+'.json');
  let sessionToken=null, collecting=false;
  function clearCredentials(){for(const id of ['cred-tenancy','cred-user','cred-fingerprint','cred-key','cred-passphrase','cred-home','cred-regions'])$(id).value='';}
  function collectionStatus(text){$('collect-status').textContent=text;$('collect-status').hidden=!text;}
  $('collect-open').onclick=async()=>{
    clearCredentials();collectionStatus('Checking local collection helper…');sessionToken=null;$('collect-fields').disabled=true;$('collect-dialog').showModal();
    if(location.protocol!=='http:' || location.hostname!=='127.0.0.1'){
      collectionStatus('Collection requires the local helper. From the toolkit folder run: python -m oci_admin.web_server, then open its http://127.0.0.1 URL.');return;
    }
    try{
      const response=await fetch('/api/session',{cache:'no-store',credentials:'omit',signal:AbortSignal.timeout(5000)});
      if(!response.ok)throw Error('helper');const data=await response.json();
      if(!data.sdk_available){collectionStatus('Install the optional Oracle SDK with: python -m pip install -e ".[live]", then start python -m oci_admin.web_server using that Python environment.');return;}
      if(typeof data.token!=='string')throw Error('helper');sessionToken=data.token;$('collect-fields').disabled=false;collectionStatus('Credentials are used for this attempt only. No OCI profile or key file is created.');
    }catch{collectionStatus('The local collection helper is unavailable. Stop the basic HTTP server and run: python -m oci_admin.web_server');}
  };
  $('collect-close').onclick=()=>{if(!collecting){clearCredentials();sessionToken=null;$('collect-dialog').close();}};
  $('collect-dialog').addEventListener('cancel',event=>{if(collecting)event.preventDefault();else{clearCredentials();sessionToken=null;}});
  $('collect-dialog').addEventListener('close',()=>{if(!collecting){clearCredentials();sessionToken=null;}});
  $('collect-form').addEventListener('submit',async event=>{
    event.preventDefault();if(collecting || !sessionToken)return;
    const services=['adb','oic','buckets'].filter(s=>$('collect-'+s).checked);
    if(!services.length){collectionStatus('Choose at least one service.');return;}
    let payload={tenancy_ocid:$('cred-tenancy').value.trim(),user_ocid:$('cred-user').value.trim(),fingerprint:$('cred-fingerprint').value.trim(),private_key:$('cred-key').value,
      passphrase:$('cred-passphrase').value,home_region:$('cred-home').value.trim(),regions:$('cred-regions').value.split(/[\s,]+/).filter(Boolean),services,
      include_identity:$('collect-identity').checked,bucket_details:$('collect-bucket-details').checked};
    let body=JSON.stringify(payload);payload=null;clearCredentials();
    collecting=true;$('collect-fields').disabled=true;$('collect-close').disabled=true;
    collectionStatus('Reading OCI inventory… Credentials have cleared from the form. Collection may take several minutes; the signing worker exits afterward.');
    try{
      // The server enforces this exact origin and token. Never send a key to a hosted site.
      const response=await fetch('/api/snapshot',{method:'POST',credentials:'omit',cache:'no-store',headers:{'Content-Type':'application/json','X-OCI-Session':sessionToken},body});
      body=null;const result=await response.json();
      if(!response.ok || !result.snapshot){collectionStatus((result.error || 'Collection failed.')+(result.code?' Code: '+result.code:'')+' Credentials have been discarded. Close and reopen to retry.');return;}
      load(result.snapshot,'Live OCI snapshot',false);$('source-label').textContent='LIVE SNAPSHOT';$('collect-dialog').close();message('Fresh snapshot collected. Signing process exited. Use Save snapshot to keep the inventory.',true);
    }catch{collectionStatus('The local collection request failed. No key was saved. A disconnected request may continue on the helper until completion or its 10-minute limit. Close and reopen to retry.');}
    finally{body=null;payload=null;sessionToken=null;clearCredentials();collecting=false;$('collect-close').disabled=false;}
  });
  $('demo').onclick=()=>load(DEMO_SNAPSHOT,'demo.snapshot.json',true);
  $('all-compartments').onclick=()=>selectCompartment(null);$('search-all').onclick=()=>selectCompartment(null);
  for(const id of ['ocid','name-pattern','kind','region','state','exact','descendants'])$(id).addEventListener('input',()=>{page=0;render();});
  $('clear').onclick=()=>{for(const id of ['ocid','name-pattern','kind','region','state'])$(id).value='';$('exact').checked=false;page=0;render();};
  $('expand').onclick=()=>{expanded=new Set(model.order);render();};$('collapse').onclick=()=>{expanded.clear();render();};
  $('previous').onclick=()=>{page--;render();};$('next').onclick=()=>{page++;render();};
  for(const button of document.querySelectorAll('[data-sort]'))button.onclick=()=>{if(sort===button.dataset.sort)direction*=-1;else{sort=button.dataset.sort;direction=1;}page=0;render();};
  $('close-details').onclick=()=>$('details').close();
  $('copy-ocid').onclick=async()=>{try{await navigator.clipboard.writeText(currentResource.id);$('copy-ocid').textContent='Copied';}catch{const range=document.createRange();range.selectNodeContents($('detail-fields').firstChild.lastChild);window.getSelection().removeAllRanges();window.getSelection().addRange(range);$('copy-ocid').textContent='ID selected — copy manually';}};
  $('locate').onclick=()=>{let node=model.nodes.get(currentResource.compartment_id);while(node){expanded.add(node.id);node=model.nodes.get(node.compartment_id);}selected=currentResource.compartment_id;$('descendants').checked=true;page=0;$('details').close();render();document.querySelector('.tree-row.selected')?.scrollIntoView({block:'nearest',behavior:'smooth'});};
  $('export').onclick=()=>{const rows=shown.map(({key,path,...r})=>({...r,compartment_path:path}));const url=URL.createObjectURL(new Blob([JSON.stringify(rows,null,2)],{type:'application/json'}));const a=element('a');a.href=url;a.download='oci-resource-results.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
  let dragCounter=0;
  window.addEventListener('dragenter',e=>{if(e.dataTransfer.types.includes('Files')){e.preventDefault();dragCounter++;document.body.classList.add('drop-active');}});
  window.addEventListener('dragleave',()=>{dragCounter=Math.max(0,dragCounter-1);if(!dragCounter)document.body.classList.remove('drop-active');});
  window.addEventListener('dragover',e=>{if(e.dataTransfer.types.includes('Files'))e.preventDefault();});
  window.addEventListener('drop',e=>{e.preventDefault();dragCounter=0;document.body.classList.remove('drop-active');readFile(e.dataTransfer.files[0]);});
  load(DEMO_SNAPSHOT,'demo.snapshot.json',true);
})();
