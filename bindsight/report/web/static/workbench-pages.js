/* SPDX-License-Identifier: AGPL-3.0-or-later */
'use strict';
// Dynamic data is always composed as DOM nodes, never parsed as HTML.
function node(tag, attrs={}, ...children){
  const element=document.createElement(tag);
  for(const [key,value] of Object.entries(attrs)){
    if(value===null||value===undefined||value===false)continue;
    if(key==='class')element.className=value;
    else if(key.startsWith('on'))element.addEventListener(key.slice(2),value);
    else if(key==='value')element.value=value;
    else element.setAttribute(key,value===true?'':String(value));
  }
  for(const child of children.flat(Infinity))if(child!==null&&child!==undefined)element.append(child instanceof Node?child:document.createTextNode(String(child)));
  return element;
}
const N=node;
const replace=(host,...children)=>host.replaceChildren(...children.flat(Infinity).filter(child=>child!==null&&child!==undefined&&child!==false));
const para=(...children)=>N('p',{},...children);
const label=text=>N('p',{class:'eyebrow'},text);
const source= (path,title)=>N('a',{href:evidence.repository+'/blob/'+(evidence.revision||'main')+'/'+path,target:'_blank',rel:'noreferrer'},title);
const link=(href,text,cls='text-link')=>N('a',{href,class:cls},text);
const card=(...children)=>N('article',{class:'card'},...children);
const sectionCard=(...children)=>N('article',{class:'card section-gap'},...children);
const title=text=>N('h2',{},text);
const caption=(...children)=>N('p',{class:'source-caption'},...children);
const notice=text=>N('p',{class:'notice'},text);
const field=(text,element,help)=>N('div',{class:'field'},N('label',{for:element.id},text),element,help?N('small',{},help):null);
const option=(text,value=text)=>N('option',{value},text);
const button=(id,text,handler,cls='button')=>N('button',{id,class:cls,onclick:handler},text);
const heading=(...children)=>N('div',{class:'section-title'},...children);
const row=(...children)=>N('div',{class:'row'},...children);

function renderEvidence(){
  const s=evidence.study,c=evidence.calibration;
  if(!s?.recall?.all?.at_k?.['recall@20']?.wilson||!s.gap?.n_clusters){$('evidence-content').replaceChildren(N('div',{class:'empty'},'The complete committed study is unavailable in this installation.'));return;}
  const r=s.recall.all.at_k['recall@20'].wilson,g=s.gap,sp=s.specificity,primary=s.primary_interval?.wilson;
  const stat=(name,value,detail)=>N('div',{},N('span',{},name),N('strong',{},value),N('small',{},detail));
  const filter=N('select',{id:'cohort-filter',class:'filter'},option('All scored cohorts','all'),[...new Set(s.pairs.map(p=>p.project))].sort().map(p=>option(p)));
  const body=N('tbody',{id:'pair-rows'});
  function drawPairs(){body.replaceChildren(...s.pairs.filter(p=>filter.value==='all'||p.project===filter.value).map(p=>N('tr',{},N('td',{},p.symbol),N('td',{},p.project.replace('TCGA-','')),N('td',{},N('span',{class:'tag'},p.tier)),N('td',{},p.rank==null?'—':p.rank+' / '+p.shortlist_size),N('td',{},number(p.log2fc,2)),N('td',{},number(p.p_decoy_bh)),N('td',{},String(p.outcome_class||'').replaceAll('_',' ')))));}
  filter.addEventListener('change',drawPairs);drawPairs();
  $('evidence-content').replaceChildren(
    N('div',{class:'evidence-stats'},stat('TCGA cohorts',s.projects,'Patient-matched samples'),stat('Declared panel',s.pairs.length,'Antigen–cohort pairs'),stat('Recall at rank 20',r.numerator+' / '+r.denominator,'Approved-agent pair denominator'),stat('Matched-decoy tests',s.decoy_adjusted+' / '+s.pairs.length,'Survive multiple-test correction')),
    N('div',{class:'grid-two section-gap'},
      card(label('ORDERING · POSITIVE SIGNAL'),title('Higher standing in the relevant indication.'),N('div',{class:'big-number'},number(g.point)),para('Mean within-antigen difference; 95% bootstrap interval ',N('strong',{},number(g.low)+'–'+number(g.high)),', over '+g.n_clusters+' antigens.'),sp?.p_value!=null?para('A separate '+sp.n_antigens+'-antigen permutation test gives mean standing '+number(sp.observed)+', p = '+Number(sp.p_value).toExponential(3)+' across '+sp.n_permutations.toLocaleString()+' orderings. This p-value is at the design’s resolution floor and belongs to that separate test.'):notice('The separate indication permutation result is unavailable.'),caption(source('benchmarks/study/RESULTS.md','Study results and denominators'))),
      card(label('RECOVERY · LIMITED SIGNAL'),title('Absolute recall remains low.'),N('div',{class:'big-number'},r.numerator+' of '+r.denominator),para('Approved-agent pairs recovered in the first 20 ranks. Pair-level Wilson 95% interval: ',N('strong',{},number(r.low)+'–'+number(r.high)),'. These pairs include repeated antigens.'),primary?para('The independent one-cohort-per-antigen analysis recovers '+primary.numerator+' of '+primary.denominator+', with Wilson 95% interval '+number(primary.low)+'–'+number(primary.high)+'.'):null,para(s.decoy_nominal+' of '+s.pairs.length+' comparisons are nominally significant against abundance- and standard-error-matched decoys; '+s.decoy_adjusted+' survive Benjamini–Hochberg correction.'),caption('“Approved-agent” describes the benchmark tier, not approval in every listed cancer or proof that an individual target is suitable.'))),
    sectionCard(heading(N('div',{},label('THE DECLARED PANEL'),title('Inspect each antigen–cohort pair.')),field('Cohort',filter)),caption('Shortlist ranks and adjusted decoy p-values answer different questions. An absent shortlist rank is shown as “—”.'),N('div',{class:'table-wrap'},N('table',{class:'data-table'},N('thead',{},N('tr',{},['Antigen','Cohort','Tier','Shortlist rank','log₂ fold change','Decoy p · BH','Outcome'].map(t=>N('th',{},t)))),body)))
  );
  if(evidence.numerical_validation?.length){
    const audits=evidence.numerical_validation;
    $('evidence-content').prepend(sectionCard(
      label('RNA-SEQ · NUMERICAL AUDIT'),title('Reproducibility checks, with their limits visible.'),
      para('Fresh fits on public TCGA-KIRC counts check repeatability, contrast reversal, sample ordering and sample identifiers. Current input ordering uses modeled covariates and counts, so changing sample names preserves the same numerical input. This does not establish backend order stability, biological validity or equivalence to R DESeq2.'),
      N('div',{class:'source-list'},audits.map(a=>source(a.source,a.label+' · '+a.genes_tested.toLocaleString()+' genes · '+(a.passed?'checks passed':'checks failed')))),
      ...audits.map(a=>para(a.label+': '+(Number.isInteger(a.classification_changes)?a.classification_changes+' significance classifications changed when sample identifiers were renamed. ':'Classification-change counts are unavailable. ')+(a.failed_checks.some(c=>c.startsWith('relabel_samples:'))?'Numerical differences exceeded the recorded tolerance.':''))),
      notice('Dispersion regularization and minimum fitted means were corrected. Earlier failed checks remain available, and independent R estimates still differ. The historical multi-cohort study below has not been regenerated with these corrections.'),
      caption(source('docs/validation-status.md','Read the independent comparison, validation status and hardware limits'))
    ));
  }
  if(c?.paired_interval&&Number.isFinite(c.design_pass_rate)&&Number.isFinite(c.scramble_pass_rate)){
    const figure=N('div',{id:'paired-figure'});
    const cluster=c.backbone_analysis?.design_vs_shuffle;
    const inference=cluster?.available?para('Mean paired difference: ',N('strong',{},number(cluster.mean)),' (95% backbone-cluster bootstrap interval '+number(cluster.low)+' to '+number(cluster.high)+'). Exact cluster sign-flip p = '+number(cluster.exact_signflip_p)+', across '+cluster.n_clusters+' backbones and '+cluster.n_pairs+' sequence pairs.'):notice('Backbone-cluster inference is unavailable in this copy; a sequence-pair interval should not be treated as independent-backbone evidence.');
    $('evidence-content').append(sectionCard(N('div',{class:'grid-two'},N('div',{},label('DESIGN CALIBRATION · PAIRED CONTROL'),title('The paired control does not establish a design advantage.'),para(N('strong',{},Math.round(c.design_pass_rate*100)+'%'),' of designs and ',N('strong',{},Math.round(c.scramble_pass_rate*100)+'%'),' of their own sequence shuffles crossed ipTM '+c.threshold+' under the seeded, '+c.sampling_noise.draws_per_binder+'-draw protocol.'),inference,para(c.n_designs_above_scramble+' of '+c.n_pairs+' designs outscored their shuffle. The earlier threshold-crossing rate is withdrawn as a measure of design quality. These controls are computational; the shuffles are not experimentally established nonbinders.'),caption('The current interval preserves shared-backbone dependence. Historical sequence-pair calculations remain in the source record. ',source('benchmarks/calibration/README.md','Read the full calibration'))),figure)));
    const calibrationCard=figure.closest('article');calibrationCard.id='evidence-calibration';calibrationCard.classList.add('calibration-card');$('evidence-content').insertBefore(calibrationCard,$('evidence-content').children[1]);
    drawCalibration(figure,c);
  }
}
function drawCalibration(host,c){
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 440 344');svg.setAttribute('class','paired-chart');svg.setAttribute('role','img');svg.setAttribute('aria-label','Paired ipTM scores of designed sequences and their shuffled controls');
  const add=(tag,attrs,text)=>{const e=document.createElementNS(svg.namespaceURI,tag);for(const[k,v]of Object.entries(attrs))e.setAttribute(k,String(v));if(text!==undefined)e.textContent=String(text);svg.append(e);};
  const y=v=>288-v*226;
  add('title',{},'Each line connects a design to its own sequence shuffle');
  for(const v of [0,.25,.5,.75,1]){add('line',{x1:54,x2:407,y1:y(v),y2:y(v),stroke:'#e0e7d8'});add('text',{x:13,y:y(v)+4,class:'chart-label'},v.toFixed(2));}
  add('line',{x1:54,x2:407,y1:y(c.threshold),y2:y(c.threshold),stroke:'#aa782e','stroke-dasharray':'4 4'});add('text',{x:350,y:y(c.threshold)-8,class:'chart-label'},c.threshold);
  for(const p of c.pairs||[])if(Number.isFinite(p.design)&&Number.isFinite(p.scramble)){add('line',{x1:124,x2:328,y1:y(p.design),y2:y(p.scramble),stroke:'#b7c7ac',opacity:.65});add('circle',{cx:124,cy:y(p.design),r:4,fill:'#436b41'});add('circle',{cx:328,cy:y(p.scramble),r:4,fill:'#9f805b'});}
  add('text',{x:84,y:318,class:'chart-label'},'Designed');add('text',{x:292,y:318,class:'chart-label'},'Shuffled');add('text',{x:54,y:31,class:'chart-label'},'ipTM · model interface confidence');
  host.replaceChildren(svg,caption('One line per paired sequence. '+c.sampling_noise.draws_per_binder+' diffusion draws per score. This is a different protocol from the original structures page.'));
}
function renderMethods(){
  const methodData=[['01','Expression','Raw counts & sample design','PyDESeq2 · CPU'],['02','Surface targets','Annotation & target prioritisation','SURFY / UniProt · public references'],['03','Candidate design','Backbones & amino-acid sequences','RFdiffusion + ProteinMPNN · GPU'],['04','Model assessment','Predicted complexes & confidence','Boltz-2 · GPU']];
  $('methods-content').replaceChildren(
    N('article',{class:'card pipeline-card'},label('ONE CONNECTED WORKFLOW'),N('div',{class:'pipeline'},methodData.map(([n,h,p,s])=>N('div',{},N('b',{},n),N('h3',{},h),para(p),N('small',{},s))))),
    N('div',{class:'grid-two section-gap'},card(label('THE TRACEABLE RECORD'),title('Provenance across the join.'),para('The recorded TCGA-KIRC demonstration connected CA9 and CD70 target discovery to 40 designed candidates and a PROV-O record.'),para('The committed manifest and RO-Crate metadata let you inspect the stages and listed artifacts. The complete 74 MB crate is ',N('strong',{},'not in this repository'),'; the later steps back to cohort files cannot be independently followed from this snapshot.'),N('div',{class:'source-list'},source('benchmarks/provenance_join/run_manifest.jsonld','Open the recorded manifest'),source('benchmarks/provenance_join/ro-crate-metadata.json','Inspect the RO-Crate metadata'),source('benchmarks/provenance_join/README.md','Read exactly what can be verified'))),card(label('SCOPE & INTERPRETATION'),title('What this workflow can answer.'),para('Two-condition human bulk RNA-seq analysis can prioritise candidate cell-surface targets. Changes in RNA abundance do not directly measure surface protein abundance, target accessibility, or clinical safety.'),para('Protein structures and interface scores are computational outputs. Binding, specificity, and therapeutic suitability require appropriate experimental validation.'),para('The 20 ERBB2 structures on this site come from the original designer benchmark. The paired calibration uses a different seeded five-draw protocol; its scores should not be substituted for the original structure scores.'))),
    sectionCard(label('BUILT ON COMMUNITY METHODS'),title('Credit the methods. Inspect the source.'),N('div',{class:'method-links'},[['https://github.com/scverse/PyDESeq2','PyDESeq2'],['https://github.com/RosettaCommons/RFdiffusion','RFdiffusion'],['https://github.com/dauparas/ProteinMPNN','ProteinMPNN'],['https://github.com/jwohlwend/boltz','Boltz'],['https://github.com/hamedkhakzad/SURFACE-Bind','SURFACE-Bind'],['https://alphafold.ebi.ac.uk/','AlphaFold DB']].map(([url,name])=>link(url,name))),para('bindsight is developed by Mikhaeel Atef Rizk Wahba. Cite the repository and the version used, together with the upstream methods. The software has no archived DOI in this evidence snapshot.'),N('div',{class:'source-list'},source('CITATION.cff','Citation metadata'),source('LICENSING.md','Component licences'),source('ARCHITECTURE.md','Full architecture')),caption((evidence.revision?'Source snapshot '+evidence.revision+'.':'Unversioned local copy; source links lead to the current repository.')+' Structure downloads are byte-for-byte copies of the checked evidence files; each displayed hash identifies its exact file.'))
  );
}
let uploadIdentity,inputCheck,pollTimer;
async function api(path,options={}){
  const response=await fetch('/api/workbench'+path,{...options,headers:{'X-Bindsight-Token':document.body.dataset.sessionToken||'',...(options.headers||{})}});
  const body=await response.json();if(!response.ok)throw new Error(body.error||'The local application could not complete this request.');return body;
}
function renderRun(){if(localMode)renderLocalRun();else renderInstallation();}
function renderInstallation(){
  const osSelect=N('select',{id:'install-os',class:'filter'},option('Windows · Intel / AMD','windows-x64'),option('Mac · Apple silicon','macos-arm64'),option('Mac · Intel','macos-x64'),option('Linux · Intel / AMD','linux-x64'));
  const platform=navigator.platform.toLowerCase();osSelect.value=platform.includes('mac')?'macos-arm64':platform.includes('linux')?'linux-x64':'windows-x64';
  const download=N('a',{class:'button',id:'companion-download',hidden:true,download:true},'Download companion');
  const status=para('Checking available installers…');status.setAttribute('role','status');
  const details=N('div',{class:'source-caption'});
  let manifest;
  function choose(){
    download.hidden=true;
    if(!manifest)return;
    const item=manifest.platforms?.[osSelect.value];
    if(!item||!/^Bindsight-Companion-[a-z0-9-]+(?:\.exe|\.zip)?$/.test(item.filename)||!/^[a-f0-9]{64}$/.test(item.sha256)){
      status.textContent='A verified companion download for this system is not available in this release.';details.replaceChildren();return;
    }
    download.href='downloads/'+item.filename;download.hidden=false;
    status.textContent=(item.size_bytes/1024/1024).toFixed(1)+' MB · scientific packages download during approved setup';
    details.replaceChildren(N('details',{},N('summary',{},'Download verification'),para('Source '+manifest.revision),N('code',{class:'download-hash'},item.sha256)));
  }
  osSelect.addEventListener('change',choose);
  async function installers(){
    status.textContent='Checking available installers…';
    try{
      const [response,releaseResponse]=await Promise.all([fetch('downloads/companion.json',{cache:'no-store'}),fetch('release.json',{cache:'no-store'})]);
      if(!response.ok||!releaseResponse.ok)throw new Error('The companion download list could not be reached.');
      const data=await response.json(),release=await releaseResponse.json();
      if(!/^[a-f0-9]{40}$/.test(data.revision)||data.revision!==release.revision)throw new Error('The new release is being published. Please retry in a moment.');
      manifest=data;choose();
    }catch(e){status.replaceChildren(document.createTextNode(e.message+' '),button(null,'Retry',installers,'inline-link'));}
  }
  const step=(h,p)=>N('div',{class:'step'},N('div',{},N('h3',{},h),para(p)));
  $('run-content').replaceChildren(
    N('div',{class:'install-hero'},N('div',{},label('THE BINDSIGHT COMPANION'),title('Your research. Your computer.'),para('Install the companion once. It prepares the scientific workspace, checks this computer, and opens the analysis interface in your browser.'),field('Choose your computer',osSelect),download,status,details),N('div',{class:'install-spec'},N('span',{},'BASIC ANALYSIS'),N('strong',{},'Human bulk RNA-seq · CPU'),N('span',{},'PROTEIN DESIGN'),N('strong',{},'Compatible NVIDIA GPU required'),N('span',{},'COMPUTING SERVICE FEES'),N('strong',{},'None · runs on your hardware'))),
    N('div',{class:'grid-two section-gap'},card(label('ONE GUIDED SETUP'),title('Open. Approve. Start.'),N('div',{class:'steps'},step('Open the downloaded companion','Choose the version for your computer and open the downloaded application.'),step('Approve the workspace setup','The companion downloads its own Python environment and the required scientific packages. Read the actual setup progress in its window.'),step('Use the browser interface','Upload your counts and sample design, run discovery, and inspect saved results. Compatible GPU workstations can prepare the protein-design tools from the local interface.')),row(link('bindsight://open','Open installed companion','button secondary')),caption('Already installed? Approve your browser’s Open app prompt. If your browser does not offer it, open the Bindsight shortcut created during setup. Your saved analyses remain on that computer.')),
    card(label('BEFORE YOU BEGIN'),title('Clear requirements. Real results.'),para('CPU discovery works on supported Windows, Mac and Linux computers. Protein design needs the supported Linux / WSL environment and sufficient NVIDIA GPU memory. Mac GPUs do not support the current CUDA design stack.'),para('Initial setup, reference queries and GPU models need internet access and storage. Your count matrices, sample metadata and computed results stay in the local workspace; selected gene identifiers are queried against public reference services.'),notice('Hardware checks assess prerequisites. They cannot guarantee that every target fits in memory. Protein-design predictions still require laboratory validation.'),N('details',{},N('summary',{},'Source download and technical documentation'),para(link('downloads/bindsight-local.zip','Download the complete source workspace'), ' · ',link('downloads/SHA256SUMS','Source checksum')),link('https://github.com/mikhaeelatefrizk/bindsight/blob/main/docs/local-workspace.md','Read the setup and hardware guide')))));
  installers();
}
function renderLocalRun(){
  $('run-content').replaceChildren(N('div',{id:'hardware-panel',class:'card'},N('p',{class:'status-line'},'Checking this computer…')),
    sectionCard(label('01 · INPUTS'),title('Choose the experiment.'),para('Human gene-level raw counts, with one sample per design-table row. Files are transferred only to the bindsight process on this computer.'),N('div',{class:'fields'},field('Analysis name',N('input',{id:'analysis-name',maxlength:120,value:'My RNA-seq analysis'})),N('div'),field('Counts matrix',N('input',{type:'file',id:'counts-file',accept:'.tsv,.txt,.gz',class:'file-input'}),'TSV or TSV.gz · unversioned human ENSG IDs · raw integer counts'),field('Sample design',N('input',{type:'file',id:'design-file',accept:'.tsv,.txt,.gz',class:'file-input'}),'TSV or TSV.gz · sample IDs first · two-level comparison column')),N('div',{class:'row section-gap'},button('inspect-inputs','Check complete input files',inspectFiles),N('span',{id:'input-status',role:'status'})),N('div',{id:'input-error',class:'notice error section-gap',hidden:true,role:'alert'})),
    N('article',{id:'comparison-card',class:'card section-gap',hidden:true},label('02 · COMPARISON'),title('Define the scientific contrast.'),N('div',{class:'fields'},field('Comparison column',N('select',{id:'factor'})),field('Pair samples by',N('select',{id:'paired-by'},option('Unpaired biological samples','')),'Select the patient/donor column for matched samples. Each donor must have exactly one sample per condition.'),field('Condition of interest',N('select',{id:'numerator'})),field('Reference condition',N('select',{id:'denominator'})),field('Adjusted p-value threshold',N('input',{id:'fdr',type:'number',value:.05,min:.000001,max:.999999,step:.01})),field('Absolute log₂ fold-change threshold',N('input',{id:'log2fc',type:'number',value:1,min:0,step:.1}))),N('p',{id:'contrast-summary',class:'contrast-summary'}),N('div',{class:'notice section-gap'},N('strong',{},'Analysis policy'),para('At least three biological replicates per group. The extended human surfaceome is applied before enriching at most 300 significant genes. Normal-tissue expression, available safety annotations, and extracellular topology are assessed using public references. Missing annotations remain unassessed; the small historical fallback map is disabled. Both expression directions can appear, and a candidate is not a clinically validated target.')),N('div',{class:'row section-gap'},button('start-analysis','Run discovery on this computer',startAnalysis),N('span',{id:'start-status',role:'status'}))),N('article',{id:'job-panel',class:'card section-gap',hidden:true}));
  for(const id of ['counts-file','design-file'])$(id).addEventListener('change',()=>{$('comparison-card').hidden=true;uploadIdentity=undefined;});
  for(const id of ['numerator','denominator','paired-by'])$(id).addEventListener('change',updateContrastSummary);
  checkHardware();
}
function updateContrastSummary(){if(!$('contrast-summary'))return;const a=$('numerator').value,b=$('denominator').value,paired=$('paired-by').value;$('contrast-summary').textContent='Compare '+a+' with '+b+'. Positive log₂ fold change means higher expression in '+a+'. '+(paired?'Matched by '+paired+'.':'Unpaired biological samples.');}
async function checkHardware(){
  const panel=$('hardware-panel');
  try{
    const h=await api('/hardware'),dependencies=h.dependency_status;
    const metric=(v,n)=>N('div',{},N('strong',{},v),N('span',{},n));
    const capacity=value=>Number.isFinite(value)?(value/2**30).toFixed(1)+' GiB':'Not measured';
    const failures=(dependencies?.checks||[]).filter(c=>!c.usable);
    replace(panel,heading(N('div',{},label('THIS COMPUTER'),title(h.discovery_installed?'CPU analysis libraries loaded successfully.':'CPU analysis needs attention.')),N('span',{class:'tag'},h.platform+' · Python '+h.python)),
      N('div',{class:'hardware-grid'},metric(h.cpus,'Logical CPU cores'),metric(capacity(h.memory_available_bytes),'Available memory'),metric(capacity(h.disk_free_bytes),'Free workspace storage')),
      para(h.gpus.length?h.gpus.map(g=>g.name+' · '+(g.memory_mib/1024).toFixed(1)+' GiB').join('; '):'No NVIDIA GPU was detected. CPU discovery and result exploration remain available.'),
      dependencies?.error?notice(dependencies.error):null,
      failures.length?N('details',{},N('summary',{},'Library check details'),failures.map(c=>para(c.module+' · '+(c.required?'required':'optional')+': '+c.error))):null,
      failures.some(c=>!c.required)?notice('An optional library could not load. Some reference annotations may be unavailable; their coverage will be reported with the results.'):null,
      caption(h.gpu_design_note+' Dataset memory and storage are checked again before launch.'),
      dependencies?caption(dependencies.limitation):null,
      button(null,'Check again',checkHardware,'inline-link'));
    $('inspect-inputs').disabled=!h.discovery_installed;
  }catch(e){panel.replaceChildren(notice(e.message),button(null,'Retry computer check',checkHardware,'inline-link'));}
}
async function inspectFiles(){
  const counts=$('counts-file').files[0],design=$('design-file').files[0];$('input-error').hidden=true;
  if(!counts||!design){$('input-error').textContent='Choose both files first.';$('input-error').hidden=false;return;}
  $('inspect-inputs').disabled=true;$('comparison-card').hidden=true;
  try{
    for(const f of [counts,design])if(f.size>512*1024*1024)throw new Error('Each file must be no larger than 512 MB.');
    $('input-status').textContent='Saving selected files in the local workspace…';uploadIdentity=(await api('/uploads',{method:'POST'})).id;
    for(const[kind,file]of [['counts',counts],['design',design]])await api('/uploads/'+uploadIdentity+'/'+kind,{method:'PUT',headers:{'X-Filename':encodeURIComponent(file.name),'Content-Type':'application/octet-stream'},body:file});
    $('input-status').textContent='Checking every row, sample identifier, and count value…';inputCheck=await api('/uploads/'+uploadIdentity+'/inspect',{method:'POST'});
    $('input-status').textContent=inputCheck.genes.toLocaleString()+' genes · '+inputCheck.samples+' samples · complete file check passed';
    $('factor').replaceChildren(...inputCheck.factors.map(f=>option(f.name)));$('paired-by').replaceChildren(option('Unpaired biological samples',''),...inputCheck.columns.map(c=>option(c)));
    function levels(){const f=inputCheck.factors.find(f=>f.name===$('factor').value);for(const id of ['numerator','denominator'])$(id).replaceChildren(...f.levels.map(l=>option(l+' ('+f.sizes[l]+' samples)',l)));$('denominator').selectedIndex=1;updateContrastSummary();}
    $('factor').onchange=levels;levels();$('start-analysis').disabled=false;$('start-status').textContent='';$('comparison-card').hidden=false;$('comparison-card').scrollIntoView({behavior:'smooth',block:'start'});$('factor').focus({preventScroll:true});
  }catch(e){$('input-error').textContent=e.message;$('input-error').hidden=false;$('input-status').textContent='Input check did not pass.';}finally{$('inspect-inputs').disabled=false;}
}
async function startAnalysis(){
  $('start-analysis').disabled=true;$('start-status').textContent='Validating the comparison…';
  try{if(!uploadIdentity)throw new Error('Check both input files first.');const body={name:$('analysis-name').value,factor:$('factor').value,numerator:$('numerator').value,denominator:$('denominator').value,paired_by:$('paired-by').value,fdr:Number($('fdr').value),log2fc:Number($('log2fc').value)};const job=await api('/jobs/'+uploadIdentity,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});$('start-status').textContent='Analysis queued.';await watchJob(job.id);$('job-panel').scrollIntoView({behavior:'smooth',block:'start'});}catch(e){$('start-status').textContent=e.message;$('start-analysis').disabled=false;}
}
function jobActions(job){
  if(!['completed','incomplete_annotation'].includes(job.state))return[];
  const base='/api/workbench/jobs/'+job.id+'/artifact/';
  const available=job.available_artifacts||(['gpu_setup','gpu_design'].includes(job.kind)?[]:['report','candidates','manifest','deg','config','taxonomy','coverage','fit_diagnostics']);
  const names={report:'Open report',candidates:'Candidate table',manifest:'Provenance',deg:'Differential expression',config:'Analysis settings',taxonomy:'Annotation outcomes',coverage:'Annotation coverage',fit_diagnostics:'Numerical diagnostics',ranking:'Ranked designs',validated:'Prediction scores',design_archive:'Complete design files',gpu_environment:'GPU environment record',gpu_setup_receipt:'GPU setup record',source_manifest:'Source discovery provenance'};
  const actions=[];
  if(available.includes('report'))actions.push(N('a',{class:'button',href:base+'report',target:'_blank',rel:'noreferrer'},'Open report'));
  const files=available.filter(k=>k!=='report'&&names[k]);
  if(files.length)actions.push(N('details',{class:'artifact-menu'},N('summary',{},'Download results ('+files.length+')'),N('div',{class:'artifact-links'},files.map(k=>N('a',{href:base+k,download:true},names[k])))));
  if(!job.kind||job.kind==='discovery')actions.push(button(null,'Design from these targets',()=>{gpuSourceIdentity=job.id;if(location.hash==='#gpu')renderGpu();else location.hash='gpu';},'button secondary'));
  if(job.kind==='gpu_design')actions.push(button(null,'View predicted complexes',()=>showGpuResults(job.id),'button secondary'));
  if(job.kind==='gpu_setup')actions.push(button(null,'Continue to protein design',()=>{if(location.hash==='#gpu')renderGpu();else location.hash='gpu';},'button secondary'));
  return actions;
}
function jobFitDiagnostics(job){
  const fit=job.numerical_fit;if(!fit)return N('span');
  return N('div',{class:'section-gap'},N('h3',{},'Numerical fit diagnostics'),...fit.warnings.map(message=>notice(message)),N('details',{class:'log-details'},N('summary',{},fit.available?'View recorded fit details':'Fit diagnostics are unavailable'),N('ul',{},fit.details.map(message=>N('li',{},message)))),caption(fit.scope));
}
function jobResourceInfo(job){
  const admission=job.resource_admission;if(!admission)return null;
  return N('details',{class:'log-details'},N('summary',{},'Computer check · '+admission.n_cpus+' CPU worker'+(admission.n_cpus===1?'':'s')),
    para('Estimated working memory: '+(admission.estimated_memory_bytes/2**30).toFixed(1)+' GiB. Estimated working storage: '+(admission.estimated_disk_bytes/2**30).toFixed(1)+' GiB.'),
    ...(admission.warnings||[]).map(notice),caption(admission.limits));
}
async function watchJob(id,panelId='job-panel',attempt=0){
  clearTimeout(pollTimer);const panel=$(panelId);if(!panel)return;panel.hidden=false;
  try{
    const job=await api('/jobs/'+id);
    const running=['queued','running','cancelling'].includes(job.state);
    const cancel=button(null,'Cancel job',async()=>{cancel.disabled=true;try{await api('/jobs/'+id+'/cancel',{method:'POST'});watchJob(id,panelId);}catch(e){cancel.disabled=false;cancel.textContent='Cancel failed: '+e.message;}},'button secondary');
    const resume=job.kind?.startsWith('gpu_')&&['failed','interrupted','cancelled'].includes(job.state)?button(null,'Retry / resume saved work',async()=>{try{const next=await api('/jobs/'+id+'/resume',{method:'POST'});watchJob(next.id,panelId);}catch(e){panel.append(notice(e.message));}},'button secondary'):null;
    replace(panel,label('ACTUAL JOB STATUS'),heading(title(job.name),N('span',{class:'tag'},job.state.replaceAll('_',' '))),job.error?N('p',{class:'notice error'},job.error):null,job.state==='incomplete_annotation'?notice('Reference annotation was incomplete. Missing or filtered candidates must not be interpreted as a complete biological negative.'):null,jobFitDiagnostics(job),jobResourceInfo(job),caption('Progress comes from the scientific process log. Completed computation does not establish experimental binding.'),row(jobActions(job),running?cancel:null,resume),N('details',{class:'log-details',open:running||['failed','interrupted'].includes(job.state)},N('summary',{},'View the actual process log'),N('pre',{class:'job-log'},job.log||'No log has been recorded yet.')));
    if(running)pollTimer=setTimeout(()=>watchJob(id,panelId),2500);
  }catch(e){
    panel.replaceChildren(notice('The connection to this computer was interrupted. The job may still be running.'),para(e.message),button(null,'Reconnect',()=>watchJob(id,panelId),'button secondary'));
    if(attempt<3)pollTimer=setTimeout(()=>watchJob(id,panelId,attempt+1),Math.min(10000,2500*(attempt+1)));
  }
}
async function refreshRuns(){
  try{
    const{jobs}=await api('/jobs');
    $('runs-content').replaceChildren(...(jobs.length?jobs.map(job=>sectionCard(heading(N('div',{},label(new Date(job.created_at).toLocaleString()),title(job.name)),N('span',{class:'tag'},job.state.replaceAll('_',' '))),para(job.kind==='gpu_setup'?'Local GPU environment setup':job.kind==='gpu_design'?'Protein design and structure prediction':Number(job.genes).toLocaleString()+' genes · '+job.samples+' samples · '+job.contrast[1]+' versus '+job.contrast[2]),row(jobActions(job),button(null,'View job',()=>{location.hash='run';watchJob(job.id);},'inline-link')))):[N('div',{class:'empty'},'No analyses have been started in this workspace. Choose “New analysis” to begin.')]));
  }catch(e){$('runs-content').replaceChildren(notice(e.message),button(null,'Retry',refreshRuns,'button secondary'));}
}
