(function (root) {
  'use strict';
  function normalize(input) {
    const data = input?.inventory ? (input.inventory.value ?? input.inventory) : input;
    if (!data || data.schema_version !== 1 || !data.tenancy?.id || !Array.isArray(data.compartments) || !Array.isArray(data.resources)) throw Error('Choose a toolkit snapshot (schema_version 1) with tenancy, compartments and resources.');
    const nodes = new Map();
    for (const c of data.compartments) {
      if (!c || typeof c.id !== 'string' || typeof c.name !== 'string' || nodes.has(c.id)) throw Error('Compartment IDs must be present and unique, and names must be strings.');
      nodes.set(c.id, {...c, children: [], own: [], total: 0, descendants: 0});
    }
    if (!nodes.has(data.tenancy.id)) nodes.set(data.tenancy.id, {id:data.tenancy.id, name:data.tenancy.name || 'Tenancy', compartment_id:null, children:[], own:[], total:0, descendants:0});
    for (const r of data.resources) {
      if (!r || !['id','name','kind','region','compartment_id'].every(k => typeof r[k] === 'string')) throw Error('Each resource needs string id, name, kind, region and compartment_id fields.');
      if (!nodes.has(r.compartment_id)) nodes.set(r.compartment_id, {id:r.compartment_id, name:'Uncollected compartment', compartment_id:null, children:[], own:[], total:0, descendants:0, unresolved:true});
    }
    // Reject cycles before building paths; never silently drop cyclic/orphan records.
    const finished = new Set();
    for (const id of nodes.keys()) {
      const seen = new Set(); let current = id;
      while (nodes.has(current) && !finished.has(current)) {
        if (seen.has(current)) throw Error('The compartment hierarchy contains a cycle.');
        seen.add(current); current = nodes.get(current).compartment_id;
      }
      for (const item of seen) finished.add(item);
    }
    const roots = [];
    for (const node of nodes.values()) {
      const parent = nodes.get(node.compartment_id);
      if (parent) parent.children.push(node.id);
      else { roots.push(node.id); if (node.compartment_id) node.unresolved = true; }
    }
    const collator = new Intl.Collator(undefined, {numeric:true,sensitivity:'base'});
    const byName = (a,b) => collator.compare(nodes.get(a).name,nodes.get(b).name);
    roots.sort(byName); for (const n of nodes.values()) n.children.sort(byName);
    const order = [], pending = roots.map(id => [id,'',0]).reverse();
    while (pending.length) {
      const [id,prefix,depth] = pending.pop(), n = nodes.get(id);
      n.path = prefix ? prefix + '/' + n.name : (n.unresolved ? '[unresolved]/' : '') + n.name;
      n.depth = depth; order.push(id);
      for (const child of [...n.children].reverse()) pending.push([child,n.path,depth+1]);
    }
    const keys = new Set();
    const resources = data.resources.map(r => {
      const key = JSON.stringify([r.kind,r.region,r.id]);
      if (keys.has(key)) throw Error('Duplicate resource identity in snapshot: ' + r.id);
      keys.add(key); const row = {...r,key,path:nodes.get(r.compartment_id).path};
      nodes.get(r.compartment_id).own.push(row); return row;
    });
    for (const id of [...order].reverse()) {
      const n=nodes.get(id); n.descendants=n.children.reduce((sum,c)=>sum+nodes.get(c).total,0); n.total=n.own.length+n.descendants;
    }
    return {data,nodes,roots,order,resources};
  }
  function patternMatch(name, pattern) {
    name=name.toLocaleLowerCase(); pattern=pattern.toLocaleLowerCase();
    if (!pattern.includes('*') && !pattern.includes('?')) return name.includes(pattern);
    // Glob matching without executing user-supplied regular expressions.
    let n=0,p=0,star=-1,back=0;
    while(n<name.length) {
      if(p<pattern.length && (pattern[p]==='?' || pattern[p]===name[n])) {n++;p++;}
      else if(pattern[p]==='*') {star=p++;back=n;}
      else if(star!==-1) {p=star+1;n=++back;}
      else return false;
    }
    while(pattern[p]==='*')p++;
    return p===pattern.length;
  }
  function query(model, filters={}) {
    const ocid=(filters.ocid || '').trim().toLowerCase(), pattern=(filters.name || '').trim();
    return model.resources.filter(r => {
      if(ocid && !(filters.exact ? r.id.toLowerCase()===ocid : r.id.toLowerCase().includes(ocid)))return false;
      if(pattern && !patternMatch(r.name,pattern))return false;
      if(filters.kind && r.kind!==filters.kind)return false;
      if(filters.region && r.region!==filters.region)return false;
      if(filters.state && (r.state || 'Not reported')!==filters.state)return false;
      return true;
    });
  }
  function subtreeIds(model,id,descendants=true) {
    if(!id)return new Set(model.nodes.keys());
    const ids=new Set([id]), pending=[id];
    while(descendants && pending.length)for(const child of model.nodes.get(pending.pop())?.children || []) {ids.add(child);pending.push(child);}
    return ids;
  }
  function matchCounts(model,rows) {
    const counts=new Map([...model.nodes.keys()].map(id=>[id,0]));
    for(const row of rows)counts.set(row.compartment_id,counts.get(row.compartment_id)+1);
    for(const id of [...model.order].reverse()) {
      const n=model.nodes.get(id);
      if(counts.has(n.compartment_id))counts.set(n.compartment_id,counts.get(n.compartment_id)+counts.get(id));
    }
    return counts;
  }
  const api={normalize,patternMatch,query,subtreeIds,matchCounts};
  if(typeof module!=='undefined' && module.exports)module.exports=api;
  else root.OCIExplorer=api;
})(typeof globalThis!=='undefined'?globalThis:this);
