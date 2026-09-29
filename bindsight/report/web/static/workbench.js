/* SPDX-License-Identifier: AGPL-3.0-or-later */
'use strict';
const localMode = document.body.dataset.local === 'true';
const $ = (id) => document.getElementById(id);
const number = (n, digits=3) => n === null || n === undefined ? '—' : Number(n).toFixed(digits);
let evidence, molecularViewer, activeBinder, selectionGeneration = 0, rotating = false;
function switchPage(route) {
  let [page,anchor] = route.split('/');
  if (!$('page-' + page)) page = 'structures';
  document.querySelectorAll('.page').forEach(el => { el.hidden = el.id !== 'page-' + page; });
  document.querySelectorAll('[data-page]').forEach(el => {
    const active = el.dataset.page === page;
    el.classList.toggle('active', active);
    if (active) el.setAttribute('aria-current','page'); else el.removeAttribute('aria-current');
  });
  if (page === 'structures' && molecularViewer) { molecularViewer.resize(); molecularViewer.render(); }
  if (page === 'runs' && localMode && typeof refreshRuns === 'function') refreshRuns();
  const names={structures:'Structure explorer',evidence:'The evidence',methods:'Methods & sources',run:localMode?'New analysis':'Run locally',runs:'Your analyses'};
  document.title=names[page]+' · bindsight';
  if(anchor==='calibration'&&page==='evidence')requestAnimationFrame(()=>$('evidence-calibration')?.scrollIntoView({block:'start'}));
  else window.scrollTo({top:0,behavior:'instant'});
}
window.addEventListener('hashchange', () => switchPage(location.hash.slice(1)));
function binderLabel(id) { const m = /binder_(\d+)_seq(\d+)/.exec(id); return m ? `Design ${String(+m[1]+1).padStart(2,'0')} · ${+m[2]+1}` : id; }
async function selectBinder(binder) {
  activeBinder = binder;
  const generation = ++selectionGeneration;
  document.querySelectorAll('.binder-item').forEach(el => { const chosen = el.dataset.id === binder.id; el.classList.toggle('selected', chosen); el.setAttribute('aria-pressed',String(chosen)); });
  $('selected-name').textContent = binderLabel(binder.id);
  $('iptm').textContent = number(binder.iptm);
  $('confidence-fill').style.width = (Number.isFinite(binder.iptm)?Math.max(0,Math.min(1,binder.iptm))*100:0)+'%';
  $('pae').textContent = number(binder.pae, 1);
  $('sequence-length').textContent = binder.length ? `${binder.length} aa` : '—';
  $('structure-hash').textContent = binder.sha256;
  $('download-cif').href = binder.structure;
  $('download-fasta').href = binder.fasta;
  $('download-fasta').hidden = !binder.fasta;
  $('structure-source').href = `${evidence.repository}/blob/${evidence.revision}/benchmarks/designer_benchmark/binders/${binder.id}_complex.cif`;
  $('viewer-status').hidden = false;
  $('viewer-status').textContent = 'Loading the committed predicted complex…';
  if (molecularViewer) molecularViewer.removeAllModels();
  try {
    if (!window.$3Dmol) throw new Error('The molecular viewer could not load. You can still download the original structure.');
    const response = await fetch(binder.structure);
    if (!response.ok) throw new Error('This structure could not be loaded. Try again or inspect the original file.');
    const cif = await response.text();
    if (generation !== selectionGeneration) return;
    if (!molecularViewer) molecularViewer = $3Dmol.createViewer($('molecule'), {backgroundColor:'#17362e',backgroundAlpha:0,antialias:true});
    molecularViewer.addModel(cif, 'cif');
    molecularViewer.setStyle({chain:'T'}, {cartoon:{color:'#b0cbc0',opacity:1}});
    molecularViewer.setStyle({chain:'B'}, {cartoon:{color:'#ddf3a9'}});
    molecularViewer.zoomTo(); molecularViewer.zoom(1.75); molecularViewer.resize(); molecularViewer.render();
    molecularViewer.spin(false); rotating = false; $('spin').textContent = 'Rotate'; $('spin').setAttribute('aria-pressed','false');
    $('viewer-status').hidden = true;
    return {id:binder.id,loaded:true,iptm:binder.iptm};
  } catch (error) { if (generation === selectionGeneration) $('viewer-status').textContent = error.message; }
}
$('spin').addEventListener('click', () => { if (!molecularViewer) return; rotating = !rotating; molecularViewer.spin(rotating ? 'y' : false, .35); $('spin').textContent = rotating ? 'Pause' : 'Rotate'; $('spin').setAttribute('aria-pressed',String(rotating)); });
$('reset-view').addEventListener('click', () => { if (molecularViewer) { molecularViewer.zoomTo(); molecularViewer.zoom(1.75); molecularViewer.render(); } });
window.addEventListener('resize', () => { if (molecularViewer) { molecularViewer.resize(); molecularViewer.render(); } });
async function boot() {
  if(localMode)renderRun();
  try {
    const response = await fetch(localMode ? '/api/workbench/evidence' : 'evidence.json');
    if (!response.ok) throw new Error('The evidence dataset is unavailable. No substitute results are shown.');
    evidence = await response.json();
    $('evidence-version').textContent = `Evidence source · ${evidence.revision.slice(0,7)}`;
    $('binder-count').textContent = evidence.binders.length;
    $('binder-list').replaceChildren();
    evidence.binders.forEach(b => {
      const button = document.createElement('button'); button.className = 'binder-item'; button.dataset.id = b.id;
      button.replaceChildren(node('strong',{},binderLabel(b.id)),node('small',{},b.id.replace('P04626_','')),node('span',{class:'score'},number(b.iptm)));
      button.addEventListener('click', () => selectBinder(b)); $('binder-list').append(button);
    });
    if (typeof renderEvidence === 'function') renderEvidence();
    if (typeof renderMethods === 'function') renderMethods();
    if (!localMode && typeof renderRun === 'function') renderRun();
    switchPage(location.hash.slice(1) || 'structures');
    if (evidence.binders.length) await selectBinder(evidence.binders[0]);
    else $('viewer-status').textContent = 'No committed structures are available in this installation.';
    registerResearchTools();
  } catch(error) { $('load-error').textContent = error.message; $('load-error').hidden = false; }
}
boot();

function registerResearchTools(){
  const context=document.modelContext;if(!context?.registerTool)return;
  const lifecycle=new AbortController();
  const register=tool=>{try{Promise.resolve(context.registerTool(tool,{signal:lifecycle.signal})).catch(()=>{});}catch{}};
  register({name:'read_committed_designs',title:'Read committed protein designs',description:'Read the real design identifiers and model confidence scores in the visible Bindsight library. These are computational predictions, not experimental binding results.',inputSchema:{type:'object',properties:{},additionalProperties:false},annotations:{readOnlyHint:true,untrustedContentHint:false},execute(input){if(input&&Object.keys(input).length)throw new Error('No input fields are accepted.');return {source:evidence.source,selected:activeBinder?.id,designs:evidence.binders.map(b=>({id:b.id,iptm:b.iptm,pae:b.pae,length:b.length}))};}});
  register({name:'show_committed_design',title:'Show a committed protein complex',description:'Open the structures page and select an existing design in the visible viewer. This changes the selected design; it does not run an analysis.',inputSchema:{type:'object',properties:{id:{type:'string'}},required:['id'],additionalProperties:false},annotations:{readOnlyHint:false,untrustedContentHint:false},async execute(input){if(!input||typeof input.id!=='string'||Object.keys(input).some(k=>k!=='id'))throw new Error('Provide one design id.');const binder=evidence.binders.find(b=>b.id===input.id);if(!binder)throw new Error('That design is not in the committed library.');location.hash='structures';switchPage('structures');const result=await selectBinder(binder);return result||{id:binder.id,loaded:false,error:$('viewer-status').textContent};}});
  window.addEventListener('pagehide',()=>lifecycle.abort(),{once:true});
}

if($('refresh-runs'))$('refresh-runs').addEventListener('click',refreshRuns);
