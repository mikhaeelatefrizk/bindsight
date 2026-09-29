/* SPDX-License-Identifier: AGPL-3.0-or-later */
'use strict';
let gpuSourceIdentity='',gpuRenderGeneration=0;
let gpuResultsIdentity='';

async function renderGpu(){
  const generation=++gpuRenderGeneration,host=$('gpu-content');
  if(!host)return;
  host.replaceChildren(card(para('Checking this computer and its scientific environment…')));
  try{
    const [ready,{jobs}]=await Promise.all([api('/gpu/readiness'),api('/jobs')]);
    if(generation!==gpuRenderGeneration)return;
    const setup=card(label('01 · PREPARE THIS COMPUTER'),heading(title(ready.setup.state==='ready'?'GPU environment prepared.':'Check before you compute.'),N('span',{class:'tag'},ready.ready?'Environment checked':ready.setup.job_id?'Preparation running':ready.hardware_eligible?'Preparation needed':'Hardware requirement')),
      para(ready.gpus.length?ready.gpus.map(g=>g.name+' · '+(g.memory_mib/1024).toFixed(1)+' GiB').join('; '):'No compatible NVIDIA device was detected.'),
      ...ready.blockers.map(notice),caption(ready.note));
    const jobPanel=N('article',{id:'gpu-job-panel',class:'card section-gap',hidden:true});
    if(ready.can_setup&&!ready.ready){
      const consent=N('input',{type:'checkbox',id:'gpu-setup-consent'});
      const start=button(null,'Prepare GPU tools',async()=>{
        start.disabled=true;
        try{const job=await api('/gpu/setup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({approved:true})});await watchJob(job.id,'gpu-job-panel');jobPanel.scrollIntoView({behavior:'smooth',block:'start'});}
        catch(e){setup.append(notice(e.message));start.disabled=false;}
      });
      start.disabled=true;consent.addEventListener('change',()=>{start.disabled=!consent.checked;});
      setup.append(para('One-time preparation downloads RFdiffusion, ProteinMPNN, Boltz and their dependencies into a private environment. Keep this app open. At least 60 GiB of free disk space is required; the first prediction also downloads model weights.'),N('label',{class:'consent-line',for:'gpu-setup-consent'},consent,N('span',{},'Allow Bindsight to download and install the listed GPU tools on this computer.')),row(start));
    }
    setup.append(button(null,'Check again',renderGpu,'inline-link'));
    const completed=jobs.filter(j=>(!j.kind||j.kind==='discovery')&&['completed','incomplete_annotation'].includes(j.state));
    const experiments=N('select',{id:'gpu-source'},option('Choose a completed discovery analysis',''),completed.map(j=>option(j.name,j.id)));
    if(completed.some(j=>j.id===gpuSourceIdentity))experiments.value=gpuSourceIdentity;
    const targetsHost=N('div',{id:'gpu-targets',class:'section-gap'});
    const selection=card(label('02 · SELECT THE SCIENTIFIC INPUT'),title('Continue from your discovery.'),para('Choose targets from a completed RNA-seq analysis. Only targets with the required recorded structure and extracellular residue ranges can proceed.'),completed.length?field('Discovery analysis',experiments):para('No completed discovery analyses are available. ',link('#run','Start an RNA-seq analysis')),targetsHost);
    experiments.addEventListener('change',()=>{gpuSourceIdentity=experiments.value;renderGpuTargets(gpuSourceIdentity,ready,targetsHost);});
    host.replaceChildren(setup,jobPanel,N('div',{class:'section-gap'},selection));
    if(ready.setup.job_id)watchJob(ready.setup.job_id,'gpu-job-panel');
    if(experiments.value)renderGpuTargets(experiments.value,ready,targetsHost);
    if(gpuResultsIdentity)renderGpuResults(gpuResultsIdentity,host);
  }catch(e){if(generation===gpuRenderGeneration)host.replaceChildren(notice(e.message),button(null,'Retry hardware check',renderGpu,'button secondary'));}
}

function showGpuResults(identity){
  gpuResultsIdentity=identity;
  if(location.hash==='#gpu')renderGpu();else location.hash='gpu';
}

async function renderGpuResults(identity,host){
  const results=sectionCard(label('COMPUTED ON THIS COMPUTER'),title('Inspect your predicted complexes.'));
  host.append(results);
  try{
    const data=await api('/jobs/'+identity+'/structures');
    const select=N('select',{id:'gpu-result-structure'},data.structures.map(s=>option(s.filename,s.id)));
    const view=N('div',{class:'gpu-molecule',role:'img','aria-label':'Predicted complex from your local protein-design job'});
    let viewer;
    const status=N('p',{role:'status'}),download=N('a',{class:'button secondary',download:true},'Download original structure'),hash=N('code',{class:'download-hash'});
    results.append(para(data.note));
    if(!data.structures.length){results.append(notice('No completed predicted complex files are available for this job. Inspect the report and actual log.'));return;}
    results.append(field('Predicted complex',select),view,status,row(download,button(null,'Reset view',()=>{if(viewer){viewer.zoomTo();viewer.render();}},'button secondary')),N('details',{},N('summary',{},'Original file checksum'),hash));
    let generation=0;
    async function loadStructure(){
      const current=++generation,item=data.structures.find(s=>s.id===select.value);
      status.textContent='Loading the actual predicted structure…';
      if(viewer)viewer.removeAllModels();
      try{
        if(!item||!['cif','pdb'].includes(item.format)||!/^[a-f0-9]{20}$/.test(item.id))throw new Error('The structure record is invalid.');
        const url='/api/workbench/jobs/'+identity+'/structures/'+item.id;
        download.href=url;hash.textContent=item.sha256;
        const response=await fetch(url);if(!response.ok)throw new Error('The saved structure could not be read.');
        const contents=await response.text();if(current!==generation||!view.isConnected)return;
        if(!window.$3Dmol)throw new Error('The viewer could not load. The original file is available to download.');
        if(!viewer)viewer=$3Dmol.createViewer(view,{backgroundColor:'#17362e',antialias:true});
        viewer.addModel(contents,item.format);viewer.setStyle({},{cartoon:{color:'spectrum'}});
        viewer.zoomTo();viewer.resize();viewer.render();status.textContent='Computed prediction · colours show residue order, not measured binding.';
      }catch(e){status.replaceChildren(document.createTextNode(e.message+' '),button(null,'Retry',loadStructure,'inline-link'));}
    }
    select.addEventListener('change',loadStructure);loadStructure();
  }catch(e){results.append(notice(e.message),button(null,'Retry results',()=>{results.remove();renderGpuResults(identity,host);},'button secondary'));}
}

async function renderGpuTargets(identity,ready,host){
  host.replaceChildren();if(!identity)return;
  host.append(para('Reading the actual discovery artifacts…'));
  try{
    const data=await api('/jobs/'+identity+'/targets');
    if(identity!==gpuSourceIdentity)return;
    const boxes=[];
    const rows=data.targets.map(t=>{
      const checkbox=N('input',{type:'checkbox',value:t.id,disabled:!t.eligible});boxes.push(checkbox);
      return N('label',{class:'target-choice'},checkbox,N('span',{},N('strong',{},t.uniprot),para('Chain '+t.chain+' · '+(t.residues.length?t.residues.length+' specified hotspot residues':'No specified hotspots')),caption(t.eligible?'Recorded extracellular ranges: '+t.design_ranges.map(([start,end])=>start+'–'+end).join(', '):t.reasons.join(' '))));
    });
    const settings={};
    const setting=(name,text,min,max)=>{const control=N('input',{type:'number',id:'gpu-'+name,min,max,step:1,value:ready.defaults[name]});settings[name]=control;return field(text,control);};
    const message=N('p',{role:'status'});
    const run=button(null,'Run design and prediction',async()=>{
      run.disabled=true;message.textContent='Checking the selected targets…';
      try{
        const body={target_ids:boxes.filter(b=>b.checked).map(b=>b.value)};
        if(!body.target_ids.length||body.target_ids.length>3)throw new Error('Choose one to three eligible targets.');
        for(const[name,element]of Object.entries(settings)){body[name]=Number(element.value);if(!Number.isInteger(body[name]))throw new Error('Design settings must be whole numbers.');}
        const job=await api('/jobs/'+identity+'/design',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
        message.textContent='Job queued on this computer.';
        await watchJob(job.id,'gpu-job-panel');$('gpu-job-panel').scrollIntoView({behavior:'smooth',block:'start'});
      }catch(e){message.textContent=e.message;}finally{run.disabled=!ready.ready;}
    });run.disabled=!ready.ready||!data.targets.some(t=>t.eligible);
    replace(host,data.targets.length?N('div',{class:'target-choices'},rows):notice('This discovery did not produce any targets with the required structural annotations.'),caption(data.note),N('div',{class:'fields section-gap'},setting('trajectories','Backbones per target',1,10),setting('seed','Random seed',0,2147483647),setting('binder_length_min','Minimum candidate length',40,150),setting('binder_length_max','Maximum candidate length',40,150)),
      notice('RFdiffusion and ProteinMPNN generate candidates; Boltz predicts complexes, then Bindsight ranks the recorded outputs. This consumes local GPU time and can still fail if a target exceeds available memory. These outputs do not prove binding.'),!ready.ready?para('Complete GPU preparation above before starting.'):null,row(run,message));
  }catch(e){host.replaceChildren(notice(e.message),button(null,'Retry targets',()=>renderGpuTargets(identity,ready,host),'button secondary'));}
}
