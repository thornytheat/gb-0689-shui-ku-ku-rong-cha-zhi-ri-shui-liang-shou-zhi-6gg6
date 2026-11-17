const waterState={busy:false};const feedback=document.querySelector('#message');
function pickSwitch(form){
  const sel=form.elements.curve_switch;
  if(!sel||!sel.value)return null;
  const rev=(window.REVISIONS||[]).find(r=>r.effective_at===sel.value);
  if(!rev)return null;
  return {effective_at:rev.effective_at,curve:rev.curve};
}
const form=document.querySelector('#water-form');form?.addEventListener('submit',async e=>{e.preventDefault();if(waterState.busy)return;waterState.busy=true;const b=form.querySelector('button');b.disabled=true;b.textContent='核算中';try{const params={max_gap_hours:form.elements.max_gap_hours.value,tolerance_m3:form.elements.tolerance_m3.value};const sw=pickSwitch(form);if(sw)params.curve_switch=sw;let options;if(form.elements.file.files[0]){const f=new FormData();f.append('file',form.elements.file.files[0]);f.append('params',JSON.stringify(params));options={method:'POST',body:f};}else options={method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:form.elements.text.value,params})};const res=await fetch('/api/runs',options);const result=await res.json();if(!res.ok)throw Error(result.message);location.assign('/m/5?run='+result.manifest.run_id);}catch(err){feedback.textContent=err.message;}finally{waterState.busy=false;b.disabled=false;b.textContent='重算水账';}});
const review=document.querySelector('#review-form');review?.addEventListener('submit',async e=>{e.preventDefault();try{const res=await fetch('/api/review/'+review.dataset.run,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version:Number(review.dataset.version),decision:review.elements.decision.value})});const result=await res.json();if(!res.ok)throw Error(result.message);location.reload();}catch(err){feedback.textContent=err.message;}});
const revisionForm=document.querySelector('#revision-form');const revisionMsg=document.querySelector('#revision-message');
revisionForm?.addEventListener('submit',async e=>{e.preventDefault();try{
  const points=revisionForm.elements.new_curve.value.split(/\r?\n/).map(l=>l.trim()).filter(Boolean).map(l=>l.split(',').map(v=>v.trim()));
  const payload={curve_switch:{effective_at:revisionForm.elements.effective_at.value.trim(),curve:points}};
  const res=await fetch('/api/m2/revisions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const data=await res.json();if(!res.ok)throw Error(data.message);
  revisionMsg.textContent='改版已'+data.revision.status+'，试算批次 '+data.run_id.slice(0,12)+'，即将打开日收支页。';
  setTimeout(()=>location.assign('/m/5?run='+data.run_id),700);
}catch(err){revisionMsg.textContent=err.message;}});
