/* Same content renderer for Django web and React Native WebView. No PDF viewer. */
(() => {
  'use strict';
  const cfg = JSON.parse(document.getElementById('reader-config').textContent);
  const $ = id => document.getElementById(id);
  const NS = 'http://www.w3.org/2000/svg';
  const fontCache = new Map();
  let page = cfg.initial, payload = null, requestId = 0, zoom = 1, dirty = false, saving = false;
  const status = text => { $('status').textContent = text; };
  const url = (pattern, n) => pattern.replace('{page}', n);
  const storage = { get(k){try{return localStorage.getItem(k);}catch{return null;}}, set(k,v){try{localStorage.setItem(k,v);}catch{}} };
  const progressKey = `content-progress-${cfg.book}`;
  const svg = (tag, attrs={}) => {const el=document.createElementNS(NS,tag);for(const [k,v] of Object.entries(attrs))el.setAttribute(k,String(v));return el;};
  function shapingLayout(source){
    const layout=JSON.parse(JSON.stringify(source));
    for(const line of layout.lines){
      const joined=[];
      for(const run of line.runs){
        const previous=joined[joined.length-1];
        // PDF drop capitals can split a Hindi syllable across differently sized
        // spans. Shape touching word fragments together, not as isolated SVG text.
        if(previous&&previous.source_text&&run.source_text&&previous.font===run.font&&
          Math.abs(previous.origin[1]-run.origin[1])<1&&Math.abs(run.bbox[0]-previous.bbox[2])<1&&
          !/\s$/.test(previous.text)&&!/^\s/.test(run.text)){
          previous.text=(previous.text+run.text).replace(/अा/g,'आ').normalize('NFC');
          previous.source_text+=run.source_text;
          previous.bbox=[previous.bbox[0],Math.min(previous.bbox[1],run.bbox[1]),run.bbox[2],Math.max(previous.bbox[3],run.bbox[3])];
          previous.size=run.size;
        }else joined.push(run);
      }
      line.runs=joined;
    }
    return layout;
  }
  async function fonts(layout) {
    const map = {};
    for (const [key, spec] of Object.entries(layout.fonts || {})) {
      if (!spec.legacy && /^data:font\/(ttf|otf);base64,[A-Za-z0-9+/=]+$/.test(spec.data || '')) {
        // A PDF may reuse a font name for different subsets on different pages.
        const cacheKey = `${key}:${spec.data}`;
        if (!fontCache.has(cacheKey)) {
          const family = `BookSource${fontCache.size}`;
          const face = new FontFace(family, `url(${spec.data})`);
          fontCache.set(cacheKey, face.load().then(loaded => {document.fonts.add(loaded);return family;}).catch(() => 'BookDevanagari'));
        }
        map[key] = await fontCache.get(cacheKey);
      } else map[key] = 'BookDevanagari';
    }
    await document.fonts.load('20px BookDevanagari');
    if(layout.lines.some(line=>line.runs.some(run=>run.bold)))await document.fonts.load('700 20px BookDevanagari');
    return map;
  }
  async function render() {
    if (!payload) return;
    const currentPayload = payload;
    const layout = shapingLayout(payload.layout), names = await fonts(layout);
    if (currentPayload !== payload) return;
    const host=$('page-host'); host.replaceChildren();
    if ($('mode').value === 'flow') {
      const paper=document.createElement('div');paper.className='paper flow-paper';paper.style.fontSize=`${20*zoom}px`;
      const sizes=layout.lines.flatMap(l=>l.runs.map(r=>r.size)).sort((a,b)=>a-b);
      const base=sizes[Math.floor(sizes.length/2)]||18;
      for(const line of layout.lines){
        const row=document.createElement('p');row.className='flow-line';
        for(const run of line.runs){const span=document.createElement('span');span.textContent=run.text;span.style.fontFamily=`${names[run.font]||'BookDevanagari'}, serif`;span.style.fontSize=`${run.size/base}em`;span.style.fontWeight=run.bold?'700':'400';span.style.fontStyle=run.italic?'italic':'normal';row.append(span);}
        paper.append(row);
      }
      host.append(paper); return;
    }
    const width=Math.max(160,host.clientWidth-2)*zoom;
    const paper=document.createElement('div');paper.className='paper';paper.style.width=`${width}px`;
    const canvas=svg('svg',{viewBox:`0 0 ${layout.width} ${layout.height}`,width:'100%',role:'document','aria-label':`${cfg.title}, पृष्ठ ${page}`});
    canvas.style.aspectRatio=`${layout.width} / ${layout.height}`;
    // Text-only reader: ignore decoration even on previously extracted editions.
    for(const line of layout.lines) for(const run of line.runs){
      const node=svg('text',{x:run.origin[0],y:run.origin[1],'font-family':`${names[run.font]||'BookDevanagari'}, serif`,'font-size':run.size,'font-weight':run.bold?'700':'400','font-style':run.italic?'italic':'normal',fill:/^#[0-9a-f]{6}$/i.test(run.color||'')?run.color:'#000000'});
      node.textContent=run.text;
      if(names[run.font]==='BookDevanagari' && layout.fonts[run.font]?.legacy)node.setAttribute('font-size',run.size*.82);
      if(run.underline)node.setAttribute('text-decoration','underline');
      canvas.append(node);
    }
    paper.append(canvas);host.append(paper);
    // Preserve natural glyph proportions. Fit overly wide replacement text by
    // reducing its size uniformly, never by stretching glyphs horizontally.
    const runs=layout.lines.flatMap(line=>line.runs);
    [...canvas.querySelectorAll('text')].forEach((node,index)=>{
      const run=runs[index];
      if(!(run.confidence!==undefined||run.fit_source_width))return;
      const available=run.bbox[2]-run.bbox[0],measured=node.getComputedTextLength();
      if(available>0&&measured>available)node.setAttribute('font-size',Number(node.getAttribute('font-size'))*available/measured);
      if(available>0){node.setAttribute('x',(run.bbox[0]+run.bbox[2])/2);node.setAttribute('text-anchor','middle');}
    });
    // A vertical scrollbar can reduce available width after the page is inserted.
    // Fit again once so the default zoom does not introduce a horizontal scrollbar.
    paper.style.width=`${Math.max(160,host.clientWidth-2)*zoom}px`;
  }
  function markDirty(){dirty=true;if($('approve'))$('approve').checked=false;status('बदलाव सुरक्षित करना बाकी है।');}
  function editor(){
    if(!cfg.review)return;
    reviewProgress();
    $('review-state').textContent=payload.reviewed?'✓ Reviewed':'समीक्षा बाकी है';$('approve').checked=payload.reviewed;
    $('issues').replaceChildren();for(const issue of payload.issues||[]){const li=document.createElement('li');li.textContent=issue;$('issues').append(li);}
    $('line-editor').replaceChildren();
    payload.layout.lines.forEach((line,li)=>line.runs.forEach((run,ri)=>{
      const row=document.createElement('div');row.className='edit-line';
      const label=document.createElement('small');label.textContent=`${li+1}.${ri+1}`;row.append(label);
      const text=document.createElement('textarea');text.value=run.text;text.setAttribute('aria-label',`Line ${li+1} text`);text.disabled=!cfg.editable;
      text.oninput=()=>{run.text=text.value;markDirty();$('geometry').value=JSON.stringify(payload.layout.lines,null,2);render();};row.append(text);
      const size=document.createElement('input');size.type='number';size.min=1;size.max=1000;size.step=.1;size.value=run.size;size.setAttribute('aria-label',`Line ${li+1} font size`);size.disabled=!cfg.editable;
      size.onchange=()=>{const value=Number(size.value);if(value>=1&&value<=1000){run.size=value;markDirty();$('geometry').value=JSON.stringify(payload.layout.lines,null,2);render();}};row.append(size);
      for(const key of ['bold','italic','underline']){const label=document.createElement('label'),check=document.createElement('input');check.type='checkbox';check.checked=!!run[key];check.disabled=!cfg.editable;check.onchange=()=>{run[key]=check.checked;markDirty();$('geometry').value=JSON.stringify(payload.layout.lines,null,2);render();};label.append(check,document.createTextNode(key));row.append(label);}
      if(line.ocr_alternative){const hint=document.createElement('small');hint.textContent=`OCR तुलना: ${line.ocr_alternative}`;hint.style.width='100%';row.append(hint);}
      $('line-editor').append(row);
    }));
    $('geometry').value=JSON.stringify(payload.layout.lines,null,2);
    for(const id of ['save','save-next','approve','geometry','apply-geometry','publish','publish-direct'])$(id).disabled=!cfg.editable;
  }
  function reviewProgress(){
    if(!cfg.review||!payload?.review_summary)return;
    const summary=payload.review_summary,pending=new Set(summary.pending),available=new Set(summary.available);
    $('review-count').textContent=`${summary.approved} / ${summary.total} पृष्ठ जाँचे गए`;
    $('review-progress').value=summary.approved;
    $('next-pending').disabled=!pending.size;
    $('page-map').replaceChildren();
    for(let n=1;n<=summary.total;n++){
      const button=document.createElement('button');button.textContent=String(n);
      button.className=!available.has(n)?'unavailable':pending.has(n)?'pending':'approved';
      button.disabled=!available.has(n);
      button.setAttribute('aria-label',`पृष्ठ ${n}, ${pending.has(n)?'समीक्षा बाकी':'approved'}`);
      if(n===page)button.setAttribute('aria-current','page');
      button.onclick=()=>load(n);$('page-map').append(button);
    }
    const preview=new URL($('reader-preview').href);preview.searchParams.set('page',page);$('reader-preview').href=preview;
  }
  async function load(n){
    if(saving){status('पृष्ठ सुरक्षित हो रहा है; कृपया रुकें।');return;}
    if(dirty && !window.confirm('इस पृष्ठ के unsaved बदलाव छोड़कर आगे जाएँ?'))return;
    n=Math.max(1,Math.min(cfg.total,Number.parseInt(n,10)||1));
    const id=++requestId;status('पृष्ठ तैयार हो रहा है…');
    try{
      const response=await fetch(url(cfg.page_url,n),{credentials:'same-origin',cache:'no-store'});
      if(!response.ok)throw new Error('पृष्ठ नहीं मिला। फिर प्रयास करें।');
      const data=await response.json();if(id!==requestId)return;
      payload=data;page=n;dirty=false;
      $('page-number').value=page;$('previous').disabled=page<=1;$('next').disabled=page>=cfg.total;
      if(cfg.review){$('source').src=url(cfg.source_url,page);$('source-host').scrollTop=0;}
      editor();await render();if(id!==requestId)return;
      $('page-host').scrollTop=0;status('');
      storage.set(progressKey,String(page));
      const loc=new URL(location.href);loc.searchParams.set('page',page);history.replaceState(null,'',loc);
      if(window.ReactNativeWebView)window.ReactNativeWebView.postMessage(JSON.stringify({type:'content-page',page,edition:cfg.edition}));
    }catch(error){if(id===requestId)status(error.message);}
  }
  async function post(endpoint,data){
    const response=await fetch(endpoint,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRFToken':document.querySelector('[name=csrfmiddlewaretoken]').value},body:JSON.stringify(data)});
    const result=await response.json();if(!response.ok)throw new Error(result.error||'Request failed');return result;
  }
  async function save(next=false){
    if(!payload||!cfg.editable||saving)return;
    saving=true;
    const controls=[...document.querySelectorAll('.editor-panel input,.editor-panel textarea,.editor-panel button')];
    const disabled=controls.map(control=>control.disabled);
    controls.forEach(control=>{control.disabled=true;});
    let saved=false;
    try{
      const result=await post(url(cfg.review_url,page),{revision:payload.revision,lines:payload.layout.lines,approve:$('approve').checked});
      payload.revision=result.revision;payload.reviewed=result.reviewed;payload.review_summary=result.review_summary;dirty=false;saved=true;
      status(result.reviewed?'पृष्ठ approved और सुरक्षित है।':'Draft सुरक्षित है; approval बाकी है।');
    }catch(error){status(error.message);}
    finally{saving=false;controls.forEach((control,index)=>{control.disabled=disabled[index];});}
    if(saved){editor();if(next&&page<cfg.total)await load(page+1);}
  }
  $('previous').onclick=()=>load(page-1);$('next').onclick=()=>load(page+1);$('page-number').onchange=e=>load(e.target.value);
  $('mode').onchange=()=>{zoom=1;render();};$('smaller').onclick=()=>{zoom=Math.max(.6,zoom-.15);render();};$('larger').onclick=()=>{zoom=Math.min(3,zoom+.15);render();};
  $('theme').onchange=e=>{document.body.dataset.theme=e.target.value;storage.set('content-theme',e.target.value);};$('theme').value=storage.get('content-theme')||'light';document.body.dataset.theme=$('theme').value;
  for(const chapter of cfg.chapters){const option=document.createElement('option');option.value=chapter.start_page;option.textContent=chapter.title;$('chapter').append(option);}$('chapter').onchange=e=>{if(e.target.value)load(e.target.value);};
  let searchId=0;
  $('search-form').onsubmit=async e=>{e.preventDefault();const id=++searchId;try{const response=await fetch(`${cfg.search_url}?q=${encodeURIComponent($('query').value)}`,{cache:'no-store'});if(!response.ok)throw new Error('खोज उपलब्ध नहीं है।');const data=await response.json();if(id!==searchId)return;$('results').replaceChildren();$('results').hidden=false;for(const hit of data.results){const button=document.createElement('button');button.textContent=`पृष्ठ ${hit.page} · ${hit.excerpt}`;button.onclick=()=>{load(hit.page);$('results').hidden=true;};$('results').append(button);}if(!data.results.length)$('results').textContent='कोई परिणाम नहीं मिला।';}catch(error){status(error.message);}};
  if(cfg.review){
    $('next-pending').onclick=()=>{const pending=payload?.review_summary?.pending||[];if(pending.length)load(pending.find(n=>n>page)||pending[0]);};
    let syncing=false;
    for(const [from,to] of [[$('source-host'),$('page-host')],[$('page-host'),$('source-host')]]){
      from.addEventListener('scroll',()=>{
        if(syncing||!$('sync-scroll').checked||$('mode').value!=='fixed')return;
        syncing=true;
        const extent=from.scrollHeight-from.clientHeight;
        to.scrollTop=extent>0?from.scrollTop/extent*(to.scrollHeight-to.clientHeight):0;
        requestAnimationFrame(()=>{syncing=false;});
      },{passive:true});
    }
    $('save').onclick=()=>save();$('save-next').onclick=()=>save(true);$('approve').onchange=()=>{dirty=true;};
    $('apply-geometry').onclick=()=>{try{const lines=JSON.parse($('geometry').value);if(!Array.isArray(lines)||lines.some(l=>!Array.isArray(l.runs)||l.runs.some(r=>typeof r.text!=='string'||!Array.isArray(r.origin)||!Array.isArray(r.bbox)||!(r.size>0))))throw new Error('Invalid lines/runs JSON');payload.layout.lines=lines;markDirty();editor();render();}catch(error){status(error.message);}};
    $('publish').onclick=async()=>{if(dirty){status('पहले इस पृष्ठ के बदलाव सुरक्षित करें।');return;}try{await post(cfg.publish_url,{});cfg.editable=false;editor();status('पुस्तक publish हो गई है। अब web और app में content reader उपलब्ध है।');}catch(error){status(error.message);}};
    $('publish-direct').onclick=async()=>{
      if(saving||dirty){status('पहले इस पृष्ठ के बदलाव सुरक्षित करें।');return;}
      $('publish-direct').disabled=true;
      try{await post(cfg.publish_url,{allow_unreviewed:true});cfg.editable=false;editor();status('पुस्तक सीधे publish हो गई है। Library → Books में Is published चालू रखें।');}
      catch(error){status(error.message);$('publish-direct').disabled=!cfg.editable;}
    };
  }
  window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
  let resizeTimer;window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(render,120);});
  if(!cfg.review&&!new URL(location.href).searchParams.has('page'))page=Number(storage.get(progressKey))||page;
  if(cfg.total)load(page);else status('पुस्तक की extraction अभी पूरी नहीं हुई है।');
})();
