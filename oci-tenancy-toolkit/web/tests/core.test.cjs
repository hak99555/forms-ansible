const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const core=require('../dist/core.js');
const fixture=JSON.parse(fs.readFileSync(path.join(__dirname,'../../examples/demo.snapshot.json'),'utf8'));
test('root, branch and leaf counts include all descendants once',()=>{
 const m=core.normalize(fixture),root=m.nodes.get(fixture.tenancy.id),prod=m.nodes.get('ocid1.compartment.oc1..prod');
 assert.equal(root.total,3);assert.equal(root.own.length,0);assert.equal(prod.total,3);assert.equal(prod.own.length,2);assert.equal(prod.descendants,1);
 assert.equal(m.nodes.get('ocid1.compartment.oc1..apps').total,1);
});
test('compound OCID, type, region and name filters',()=>{
 const m=core.normalize(fixture);
 assert.equal(core.query(m,{kind:'adb',name:'*ware*',ocid:'warehouse',region:'ca-toronto-1'}).length,1);
 assert.equal(core.query(m,{ocid:'warehouse',exact:true}).length,0);
 assert.equal(core.query(m,{ocid:fixture.resources[0].id,exact:true}).length,1);
 assert.equal(core.query(m,{state:'FAILED'})[0].kind,'oic');
 assert.equal(core.query(m,{kind:'adb',name:'ERP*'}).length,0);
});
test('case insensitive glob wildcards and literal regex punctuation',()=>{
 assert.equal(core.patternMatch('FinanceWarehouse','FINANCE'),true);
 assert.equal(core.patternMatch('FinanceWarehouse','*WARE*'),true);
 assert.equal(core.patternMatch('erp-a','erp-?'),true);
 assert.equal(core.patternMatch('erp-aa','erp-?'),false);
 assert.equal(core.patternMatch('foo.bar','foo.bar'),true);
 assert.equal(core.patternMatch('fooXbar','foo.bar'),false);
 assert.equal(core.patternMatch('a','*?*?*'),false);
});
test('select exact branch or descendants and aggregate matching counts',()=>{
 const m=core.normalize(fixture),id='ocid1.compartment.oc1..prod';
 assert.equal(core.subtreeIds(m,id,false).size,1);assert.equal(core.subtreeIds(m,id,true).size,2);
 const counts=core.matchCounts(m,core.query(m,{kind:'oic'}));
 assert.equal(counts.get(fixture.tenancy.id),1);assert.equal(counts.get(id),1);
});
test('wrapped Terraform output is accepted',()=>assert.equal(core.normalize({inventory:{value:fixture}}).resources.length,3));
test('invalid snapshots, duplicate IDs and cycles are rejected',()=>{
 assert.throws(()=>core.normalize({}),/snapshot/);
 const cycle=structuredClone(fixture);cycle.compartments[0].compartment_id=cycle.compartments[2].id;
 assert.throws(()=>core.normalize(cycle),/cycle/);
 const duplicate=structuredClone(fixture);duplicate.resources.push(duplicate.resources[0]);
 assert.throws(()=>core.normalize(duplicate),/Duplicate resource/);
});
test('uncollected compartments and parent chains remain visible',()=>{
 const data=structuredClone(fixture);data.resources[0].compartment_id='unknown';data.compartments[1].compartment_id='external';
 const m=core.normalize(data);assert.equal(m.nodes.get('unknown').total,1);
 assert.equal(m.nodes.get('ocid1.compartment.oc1..prod').unresolved,true);
 assert.equal([...m.roots].reduce((s,id)=>s+m.nodes.get(id).total,0),data.resources.length);
});
test('deep compartment chains do not rely on recursion',()=>{
 const data=structuredClone(fixture);data.resources=[];let parent=data.tenancy.id;
 for(let i=0;i<1500;i++){data.compartments.push({id:'c'+i,name:'c'+i,compartment_id:parent});parent='c'+i;}
 assert.equal(core.normalize(data).nodes.size,1503);
});
