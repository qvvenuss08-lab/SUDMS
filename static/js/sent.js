/* หนังสือส่ง: บันทึกร่างก่อนอัปโหลดทุกครั้ง แล้วส่งเมื่อไฟล์แนบสำเร็จเท่านั้น */
'use strict';
(()=>{
 const form=$('#sent-create-form');if(!form)return;
 const fields=form.elements;
 let busy=false,uploaded=new Set();const alreadySent=form.dataset.status!=='draft';
 const owner=form.dataset.ownerName;const labels={order:'คำสั่ง'+owner+' ที่ ',regulation:'ระเบียบ'+owner+' ที่ ',rule:'ข้อบังคับ'+owner+' ที่ ',announcement:'ประกาศ'+owner+(owner==='องค์การนักศึกษา'?'มหาวิทยาลัยขอนแก่น':'')+' ฉบับที่ '};
 function category(){return Object.hasOwn(labels,fields.document_type.value)?fields.document_type.value:'general';}
 function base(){return form.dataset.existingNumber?form.dataset.existingNumber.split('/')[0].replace(/[0-9]+$/,'').replace(/ว\.$/,''):labels[category()]||form.dataset.code;}
 const pageCategory=new URLSearchParams(location.search).get('category');if(!form.dataset.documentId&&Object.hasOwn(labels,pageCategory))fields.document_type.value=pageCategory;
 if(form.dataset.documentId){if(Object.hasOwn(labels,form.dataset.category))fields.document_type.value=form.dataset.category;fields.document_type.disabled=true;}
 function specialized(){
 const special=category()!=='general',keep=['owner_name','number_sequence','reservation_number','document_date','title','note','files'];
 for(const el of form.querySelectorAll('.sent-form-section .row > div')){
 const names=[...el.querySelectorAll('[name]')].map(x=>x.name);
 el.hidden=special&&!names.some(n=>keep.includes(n));
 }
 for(const section of form.querySelectorAll('.sent-form-section')){
 const has=[...section.querySelectorAll('[name]')].some(el=>keep.includes(el.name));section.hidden=special&&!has;
 }
 for(const el of form.querySelectorAll('.delivery-choice,#sent-paper-today,.sent-drop-zone ~ p'))el.hidden=special;
 if(special){fields.circular.checked=false;fields.priority.value='normal';fields.paper_today.checked=false;form.querySelector('[name="delivery_mode"][value="digital"]').checked=true;}
 for(const section of form.querySelectorAll('.sent-form-section')){const h=section.querySelector('h3');if(h&&section.querySelector('[name="note"]'))h.textContent=special?'หมายเหตุ':'ผู้รับเอกสาร (ไม่บังคับ)';}
 const send=form.querySelector('[type="submit"][value="send"]');send.textContent=special?'บันทึกเอกสาร':'บันทึกและส่ง';form.querySelector('[type="submit"][value="draft"]').textContent=special?'บันทึกร่าง':(form.dataset.documentId?'บันทึกการแก้ไขร่าง':'บันทึกร่างรอส่ง');
 }
 specialized();
 if(alreadySent){form.querySelector('[value="send"][type="submit"]').hidden=true;form.querySelector('[value="draft"][type="submit"]').textContent='บันทึกการแก้ไข';$('#sent-reserve').hidden=true;}
 // เก็บการเลือกหลายรายการไว้ใน select เดิม เพื่อใช้ API เดิมได้ครบถ้วน
 const recipientStore=fields.internal_recipient,recipientPicker=fields.internal_recipient_picker;
 function renderRecipientSelection(){
 const box=$('#selected-internal-recipients');box.replaceChildren();
 const selected=[...recipientStore.selectedOptions];
 if(!selected.length){const hint=document.createElement('span');hint.className='text-muted small';hint.textContent='หน่วยงานที่เลือกจะแสดงที่นี่';box.append(hint);}
 for(const option of selected){const chip=document.createElement('span');chip.className='selected-recipient-chip';const text=document.createElement('span');text.textContent=option.textContent;const remove=document.createElement('button');remove.type='button';remove.textContent='×';remove.setAttribute('aria-label','ลบ '+option.textContent);remove.disabled=recipientStore.disabled;remove.onclick=()=>{if(recipientStore.disabled)return;option.selected=false;renderRecipientSelection();};chip.append(text,remove);box.append(chip);}
 recipientPicker.replaceChildren();const placeholder=document.createElement('option');placeholder.value='';placeholder.textContent='— เลือกหน่วยงานเพื่อเพิ่ม —';recipientPicker.append(placeholder);
 for(const group of recipientStore.querySelectorAll('optgroup')){const copy=document.createElement('optgroup');copy.label=group.label;for(const option of group.children){const item=document.createElement('option');item.value=option.value;item.textContent=option.textContent;item.disabled=option.selected;copy.append(item);}recipientPicker.append(copy);}
 recipientPicker.value='';
 }
 recipientPicker.addEventListener('change',()=>{const value=recipientPicker.value;if(!value||recipientStore.disabled)return;const option=[...recipientStore.options].find(o=>o.value===value);if(option)option.selected=true;renderRecipientSelection();});
 renderRecipientSelection();
 function delivery(){const paper=fields.delivery_mode.value==='paper';fields.paper_today.disabled=!paper;$('#sent-paper-today').hidden=!paper;if(!paper)fields.paper_today.checked=false;}
 function number(){const selected=fields.reservation_number.value;fields.number_sequence.disabled=alreadySent||Boolean(selected);$('#sent-number-prefix').textContent=base()+(fields.circular.checked?'ว.':'');}
 async function reservations(){const all=await api('/api/numbers/sent/details?organization_id='+encodeURIComponent(form.dataset.ownerOrg));const list=all.filter(r=>(r.category||'general')===category());const selected=fields.reservation_number.value;
 fields.reservation_number.innerHTML='<option value="">ไม่ใช้เลขจอง</option>'+list.filter(r=>!r.used&&(!form.dataset.documentId||!r.document_id||String(r.document_id)===form.dataset.documentId)).map(r=>`<option value="${esc(r.number)}">${esc(r.number)} · จองโดย ${esc(r.reserved_by)}</option>`).join('');if(list.some(r=>!r.used&&r.number===selected))fields.reservation_number.value=selected;number();
 $('#sent-number-history').innerHTML='<table class="table"><thead><tr><th>เลขหนังสือ</th><th>ผู้จอง / ผู้กำหนดเลข</th><th>เวลาจอง</th><th>การใช้เลข</th></tr></thead><tbody>'+list.map(r=>`<tr><td>${esc(r.number)}</td><td>${esc(r.reserved_by)}<small>${esc({reserved:'จองเลข',manual:'กำหนดเลขเอง',auto:'ออกเลขอัตโนมัติ'}[r.source]||r.source)}</small></td><td>${esc(date(r.reserved_at))}</td><td>${r.used?'ใช้แล้ว โดย '+esc(r.used_by||'ไม่พบประวัติเดิม'):'ยังไม่ใช้'}${r.edit_url?`<br><a href="${esc(r.edit_url)}">เปิดแก้ไขเอกสาร</a>`:''}</td></tr>`).join('')+'</tbody></table>';
 }
 fields.document_type.addEventListener('change',()=>{fields.reservation_number.value='';fields.number_sequence.value='';specialized();number();reservations().catch(e=>notify(e.message,true));});
 fields.circular.addEventListener('change',number);fields.reservation_number.addEventListener('change',number);form.querySelectorAll('[name="delivery_mode"]').forEach(r=>r.addEventListener('change',delivery));number();delivery();
 if(!fields.document_date.value)fields.document_date.value=new Date(Date.now()+7*3600000).toISOString().slice(0,10);
 function files(){const list=[...fields.files.files];$('#sent-file-list').textContent=list.map(f=>`${f.name} (${(f.size/1024/1024).toFixed(2)} MB)`).join(' · ');}
 fields.files.addEventListener('change',files);
 const drop=$('#sent-drop-zone');drop.addEventListener('dragover',e=>{e.preventDefault();drop.classList.add('drag-over');});drop.addEventListener('dragleave',()=>drop.classList.remove('drag-over'));drop.addEventListener('drop',e=>{e.preventDefault();drop.classList.remove('drag-over');try{fields.files.files=e.dataTransfer.files;files();}catch(e){notify('กรุณาเลือกไฟล์ผ่านปุ่มเลือกไฟล์',true);}});
 $('#sent-reserve').onclick=async()=>{const b=$('#sent-reserve');b.disabled=true;try{const r=await api('/api/numbers/sent/reserve',{method:'POST',body:JSON.stringify({organization_id:form.dataset.ownerOrg,category:category(),circular:fields.circular.checked})});await reservations();const option=[...fields.reservation_number.options].find(o=>o.value===r.number);if(option){fields.reservation_number.value=r.number;number();}notify('จองเลข '+r.number+' แล้ว');}catch(e){notify(e.message,true);}finally{b.disabled=false;}};
 function list(name){return [...form.querySelectorAll(`[name="${name}"]`)].map(input=>input.value.trim()).filter(Boolean);}
 function payload(){const data=formData(form);
 const details={};for(const key of ['document_type','document_date','due_date','owner_name','personnel','salutation','practice','note'])details[key]=(key==='document_type'?fields.document_type.value:data[key])||'';
 details.recipient_names=list('recipient_names[]');details.external_units=list('external_units[]');details.internal_units=list('internal_units[]');details.recipient_org_ids=[];
 for(const option of fields.internal_recipient.selectedOptions){if(option.value.startsWith('unit:'))details.internal_units.push(option.value.slice(5));else details.recipient_org_ids.push(Number(option.value));}
 details.circular=fields.circular.checked;details.paper_today=fields.paper_today.checked;
 const result={title:data.title,sender:data.sender,priority:data.priority,digital_only:fields.delivery_mode.value==='digital',send_details:details,save_mode:'draft',category:['order','regulation','rule','announcement'].includes(details.document_type)?details.document_type:'general'};
 if(data.reservation_number)result.reservation_number=data.reservation_number;
 else if(data.number_sequence)result.number=base()+(details.circular?'ว.':'')+(category()==='general'?String(Number(data.number_sequence)).padStart(3,'0'):String(Number(data.number_sequence)))+'/'+form.dataset.year;
 return result;
 }
 function add(container,name,placeholder){const row=document.createElement('div');row.className='repeatable-row';const input=document.createElement('input');input.name=name;input.className='form-control';input.maxLength=300;input.placeholder=placeholder;const button=document.createElement('button');button.type='button';button.className='btn btn-light';button.dataset.removeRecipient='';button.setAttribute('aria-label','ลบรายการ');button.textContent='×';row.append(input,button);$(container).append(row);input.focus();}
 $('#add-internal-unit').onclick=()=>add('#sent-other-internal-units','internal_units[]','ชื่อหน่วยงานภายในอื่น');
 $('#add-recipient-name').onclick=()=>add('#sent-recipient-names','recipient_names[]','ชื่อหรือตำแหน่งผู้รับ');$('#add-external-unit').onclick=()=>add('#sent-external-units','external_units[]','ชื่อหน่วยงานภายนอก');
 form.addEventListener('click',event=>{const button=event.target.closest('[data-remove-recipient]');if(button)button.closest('.repeatable-row').remove();});
 $('#clear-internal-recipients').onclick=()=>{if(recipientStore.disabled)return;for(const option of recipientStore.options)option.selected=false;renderRecipientSelection();};
 form.addEventListener('submit',async e=>{e.preventDefault();if(busy)return;const mode=e.submitter?.value||'draft',selected=[...fields.files.files];$('#sent-error').textContent='';
 if(selected.length>5){$('#sent-error').textContent='แนบได้ไม่เกิน 5 ไฟล์ต่อครั้ง';return;}
 if(selected.some(f=>!['pdf','docx'].includes(f.name.split('.').pop().toLowerCase())||f.size>9.8*1024*1024||!f.size)){$('#sent-error').textContent='รองรับ PDF และ Word ที่ไม่ว่าง ขนาดไฟล์ต้องไม่เกิน 9.8 MB เพื่อให้คำขอรวมไม่เกิน 10 MB';return;}
 busy=true;const buttons=[...form.querySelectorAll('button')];buttons.forEach(b=>b.disabled=true);
 try{
   const data=payload();let id=form.dataset.documentId;
   let d=id?await api('/api/documents/'+id,{method:'PATCH',body:JSON.stringify(data)}):await api('/api/documents/sent',{method:'POST',body:JSON.stringify(data)});
   id=d.id;form.dataset.documentId=String(id);form.dataset.existingNumber=d.number;fields.number_sequence.value=Number(d.number.slice(base().length).split('/')[0].replace(/^ว\./,''));fields.reservation_number.value='';fields.number_sequence.disabled=false;
   for(const file of selected){const key=file.name+':'+file.size+':'+file.lastModified;if(uploaded.has(key))continue;const body=new FormData();body.append('file',file);await api(`/api/documents/${id}/attachments`,{method:'POST',body});uploaded.add(key);}
   if(mode==='send'&&!alreadySent)await api(`/api/documents/${id}/action`,{method:'POST',body:JSON.stringify({action:'send',note:'บันทึกและส่งหนังสือ'})});
   location.href='/documents/'+id;
 }catch(error){const id=form.dataset.documentId;$('#sent-error').innerHTML=esc(error.message)+(id?`<br>${alreadySent?'ข้อมูลอาจบันทึกแล้ว กรุณาตรวจสอบประวัติ':'ข้อมูลเก็บเป็นร่างแล้ว ยังไม่ส่งถึงปลายทาง'} <a href="/documents/${Number(id)}">เปิดร่างที่บันทึกไว้</a>`:'');notify(error.message,true);
 }finally{busy=false;buttons.forEach(b=>b.disabled=false);number();}
 });
 $('#sentModal')?.addEventListener('show.bs.modal',()=>reservations().catch(e=>notify(e.message,true)));
 if(form.dataset.documentId){if(new URLSearchParams(location.search).get('edit')==='1'&&$('#draft-edit-section')){$('#draft-edit-section').open=true;$('#draft-edit-section').scrollIntoView({block:'start'});fields.title.focus();}reservations().catch(e=>notify(e.message,true));api(`/api/documents/${form.dataset.documentId}/history`).then(d=>{if(!d.can_edit)for(const element of fields)element.disabled=true;else if(alreadySent){for(const name of ['circular','reservation_number','internal_recipient','internal_recipient_picker','number_sequence'])fields[name].disabled=true;for(const element of form.querySelectorAll('[name="delivery_mode"],#clear-internal-recipients,#add-internal-unit,#add-recipient-name,#add-external-unit,[data-remove-recipient]'))element.disabled=true;}}).catch(e=>notify(e.message,true));}
})();
